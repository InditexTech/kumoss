# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import asyncio
import dataclasses
import json

from typing import Any, cast

import litellm
from litellm import Choices, Message, ModelResponse, ResponsesAPIResponse, Usage
from litellm.router import Router
from openai import OpenAIError
from pydantic import BaseModel

from src.domains.interfaces.llm_interface import ILLMProvider
from src.domains.dto import (
    LLMResponseDTO,
    LLMMetadata,
    ToolCallDTO,
    ToolResultDTO,
    ToolDefinitionDTO,
)
from src.domains.entities.history import History
from src.domains.services.tracer_service import trace_llm
from src.infrastructure.exceptions import (
    InferenceCallAPIError,
    InferenceCallThinkingToolError,
    InferenceCallWebSearchTools,
)
from src.shared.logger import logging


class LiteLLMAdapter(ILLMProvider):
    def __init__(
        self,
        model: str,
        temperature: float,
        max_tokens: int,
        timeout: float,
        router: Router,
    ) -> None:
        self.__model = model
        self.__temperature = temperature
        self.__max_tokens = max_tokens
        self.__timeout = timeout
        self.__router = router
        self._last_invocation_params: dict[str, Any] | None = None

    @property
    def model(self) -> str:
        return self.__model

    @trace_llm
    async def inference(
        self,
        msg: str | list[ToolResultDTO],
        system_prompt: str | None = None,
        tools: list[ToolDefinitionDTO] | None = None,
        history: History = None,
        thinking: bool = False,
        web_search: bool = False,
        notice: str | None = None,
    ) -> LLMResponseDTO:
        if tools and thinking:
            raise InferenceCallThinkingToolError(
                message="Inference cannot be invoked with tools and thinking enabled.",
                error_code=400,
            )
        if web_search:
            if tools:
                raise InferenceCallWebSearchTools(
                    message="Inference cannot be invoked with tools and web search enabled.",
                    error_code=400,
                )
            if thinking:
                raise InferenceCallThinkingToolError(
                    message="Inference cannot be invoked with thinking and web search enabled.",
                    error_code=400,
                )

        model_id = self.__model
        max_tokens = self.__max_tokens
        local_history = self.__format_history(history, msg)
        if notice:
            local_history.append({"role": "user", "content": notice})

        if system_prompt:
            local_history.insert(0, {"role": "system", "content": system_prompt})

        if web_search and not self.__web_search_is_native():
            for attempt in range(4):
                try:
                    response = await self.__aresponses_web_search(
                        local_history, max_tokens
                    )
                    break
                except OpenAIError as e:
                    logging.error(f"LiteLLM aresponses provider error: {e!r}")

                logging.info(f" aresponses retry {attempt + 1}/4 in 30 seconds...")
                await asyncio.sleep(30)
            else:
                raise InferenceCallAPIError(
                    message=f"Inference calls (aresponses) to {self.__model} have been exhausted.",
                    error_code=502,
                )
        else:
            kwargs: dict[str, Any] = {
                "model": model_id,
                "messages": local_history,
                "max_tokens": max_tokens,
                "temperature": 1.0 if thinking else self.__temperature,
                "num_retries": 3,
                "timeout": self.__timeout,
            }

            if tools:
                kwargs["tools"] = self.__format_tools(tools)
                kwargs["tool_choice"] = "auto"

            if thinking:
                kwargs["reasoning_effort"] = "low"

            if web_search:
                kwargs["web_search_options"] = {"search_context_size": "medium"}

            self._last_invocation_params = kwargs
            try:
                response = cast(
                    ModelResponse,
                    await self.__router.acompletion(**kwargs, drop_params=True),
                )
            except OpenAIError as e:
                logging.error(f"LiteLLM API error: {e!r}")
                raise InferenceCallAPIError(
                    message=f"Inference call to {self.__model} failed.",
                    error_code=getattr(e, "status_code", 502),
                )

        message = response.choices[0].message
        usage: Usage | None = getattr(response, "usage", None)

        return LLMResponseDTO(
            text=message.content or "",
            metadata=LLMMetadata(
                finish_reason=self.__map_stop_reason(response.choices[0].finish_reason),
                model=response.model,
                input_tokens=usage.prompt_tokens if usage else 0,
                output_tokens=usage.completion_tokens if usage else 0,
            ),
            tool_calls=[
                ToolCallDTO(
                    id=tc.id,
                    name=tc.function.name,
                    parameters=json.loads(tc.function.arguments),
                )
                for tc in (message.tool_calls or [])
            ],
            thinking=getattr(message, "reasoning_content", None) if thinking else None,
        )

    def __web_search_is_native(self) -> bool:
        """Check if the model supports native web search."""
        model_id = self.__model
        try:
            info = litellm.get_model_info(model_id)
        except Exception:
            return False
        params = info.get("supported_openai_params") or []
        return "web_search_options" in params

    async def __aresponses_web_search(
        self, messages: list[dict[str, Any]], max_tokens: int
    ) -> ModelResponse:
        """Use aresponses to perform web search with models that don't support native web search.
        Like gpt-5-mini, gpt-5, gpt-4o, gpt-4.1, ...
        """
        model_id = self.__model

        aresponses_kwargs: dict[str, Any] = {
            "model": model_id,
            "input": messages,
            "tools": [{"type": "web_search_preview", "search_context_size": "medium"}],
            "max_output_tokens": max_tokens,
            "temperature": self.__temperature,
            "timeout": self.__timeout,
        }
        self._last_invocation_params = aresponses_kwargs
        resp = cast(
            ResponsesAPIResponse,
            await self.__router.aresponses(**aresponses_kwargs, drop_params=True),
        )

        text = ""
        for item in cast(list[Any], resp.output):
            content = getattr(item, "content", None)
            if not isinstance(content, list):
                continue
            for block in cast(list[Any], content):
                block_text = getattr(block, "text", None)
                if isinstance(block_text, str):
                    text += block_text

        usage = resp.usage
        return ModelResponse(
            model=resp.model or model_id,
            choices=[
                Choices(
                    index=0,
                    message=Message(content=text, role="assistant"),
                    finish_reason="stop",
                )
            ],
            usage=Usage(
                prompt_tokens=usage.input_tokens if usage else 0,
                completion_tokens=usage.output_tokens if usage else 0,
                total_tokens=usage.total_tokens if usage else 0,
            ),
        )

    def __format_tools(self, tools: list[ToolDefinitionDTO]) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []

        for t in tools:
            output.append(
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters,
                    },
                }
            )
        return output

    def __format_tool_results(
        self, tool_results: list[ToolResultDTO]
    ) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        for result in tool_results:
            # Content MUST be a string: provider converters (e.g. Anthropic)
            # silently drop non-string content.
            payload: dict[str, Any] = (
                {"success": True, "result": result.result}
                if result.success
                else {"success": False, "error": result.error_message}
            )
            output.append(
                {
                    "role": "tool",
                    "tool_call_id": result.tool_call_id,
                    "content": json.dumps(
                        payload, ensure_ascii=False, default=self.__json_default
                    ),
                }
            )
        return output

    @staticmethod
    def __json_default(obj: Any) -> Any:
        if isinstance(obj, BaseModel):
            return obj.model_dump(mode="json")
        if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
            return dataclasses.asdict(obj)
        return str(obj)

    def __format_tool_calls(
        self, tool_calls: list[ToolCallDTO]
    ) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        for call in tool_calls:
            output.append(
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": json.dumps(call.parameters),
                    },
                }
            )
        return output

    def __format_history(
        self, history: History, last_usr_msg: str | list[ToolResultDTO]
    ) -> list[dict[str, Any]]:
        if not history:
            history = History()
        formatted_history: list[dict[str, Any]] = []
        for turn in history:
            if isinstance(turn.user, list):
                formatted_history.extend(self.__format_tool_results(turn.user))
            else:
                formatted_history.append({"role": "user", "content": turn.user})

            if turn.assistant:
                if isinstance(turn.assistant, list):
                    formatted_history.append(
                        {
                            "role": "assistant",
                            "tool_calls": self.__format_tool_calls(turn.assistant),
                        }
                    )
                else:
                    formatted_history.append(
                        {"role": "assistant", "content": turn.assistant}
                    )

        if isinstance(last_usr_msg, list):
            formatted_history.extend(self.__format_tool_results(last_usr_msg))
        else:
            formatted_history.append({"role": "user", "content": last_usr_msg})

        return formatted_history

    def __map_stop_reason(self, reason: str):
        return {
            "stop": "end_turn",
            "length": "max_tokens",
            "content_filter": "content_filter",
            "tool_calls": "tool_use",
        }.get(reason)
