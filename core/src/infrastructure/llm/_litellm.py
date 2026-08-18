# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

# pyright: reportArgumentType=false, reportOptionalMemberAccess=false
import asyncio
import json

from typing import Any

import litellm
from litellm import Router
from litellm.types.utils import ModelResponse, Choices, Message, Usage
from litellm.exceptions import APIError, RateLimitError

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
        router: Router,
    ) -> None:
        self.__model = model
        self.__temperature = temperature
        self.__max_tokens = max_tokens
        self.__router = router
        self._last_invocation_params: dict[str, Any] | None = None

    @property
    def model(self) -> str:
        return self.__model

    @trace_llm
    async def inference(
        self,
        msg: str | list[ToolResultDTO],
        system_prompt: str = None,
        tools: list[ToolDefinitionDTO] = None,
        history: History = None,
        thinking: bool = False,
        web_search: bool = False,
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

        if system_prompt:
            local_history.insert(0, {"role": "system", "content": system_prompt})

        if web_search and not self.__web_search_is_native():
            for attempt in range(4):
                try:
                    response = await self.__aresponses_web_search(
                        local_history, max_tokens
                    )
                    break
                except RateLimitError as e:
                    logging.error(f"LiteLLM aresponses rate limit error: {e.message}")
                except APIError as e:
                    logging.error(f"LiteLLM aresponses API error: {e.message}")

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
                "timeout": 120,
            }

            if tools:
                kwargs["tools"] = self.__format_tools(tools)
                kwargs["tool_choice"] = "required"

            if thinking:
                kwargs["reasoning_effort"] = "medium"

            if web_search:
                kwargs["web_search_options"] = {"search_context_size": "medium"}

            self._last_invocation_params = kwargs
            try:
                response = await self.__router.acompletion(**kwargs, drop_params=True)
            except APIError as e:
                logging.error(f"LiteLLM API error: {e.message}")
                raise InferenceCallAPIError(
                    message=f"Inference call to {self.__model} failed: {e.message}",
                    error_code=getattr(e, "status_code", 502),
                )

        message = response.choices[0].message

        return LLMResponseDTO(
            text=message.content or "",
            metadata=LLMMetadata(
                finish_reason=self.__map_stop_reason(response.choices[0].finish_reason),
                model=response.model,
                input_tokens=response.usage.prompt_tokens,
                output_tokens=response.usage.completion_tokens,
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
        self, messages: list[dict], max_tokens: int
    ) -> ModelResponse:
        """Use aresponses to perform web search with models that don't support native web search.
        Like gpt-5-mini, gpt-5, gpt-4o, gpt-4.1, ...
        """
        model_id = self.__model

        aresponses_kwargs = {
            "model": model_id,
            "input": messages,
            "tools": [{"type": "web_search_preview", "search_context_size": "medium"}],
            "max_output_tokens": max_tokens,
            "temperature": self.__temperature,
            "timeout": 120,
        }
        self._last_invocation_params = aresponses_kwargs
        resp = await self.__router.aresponses(**aresponses_kwargs, drop_params=True)

        text = ""
        for item in resp.output:
            if hasattr(item, "content"):
                for block in item.content:
                    if hasattr(block, "text"):
                        text += block.text or ""

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

    def __format_tool_results(self, tool_results: list[ToolResultDTO]) -> list[dict]:
        output: list[dict] = []
        for result in tool_results:
            output.append(
                {
                    "role": "tool",
                    "tool_call_id": result.tool_call_id,
                    "content": str(result.result)
                    if result.success
                    else result.error_message,
                }
            )
        return output

    def __format_tool_calls(self, tool_calls: list[ToolCallDTO]) -> list[dict]:
        output: list[dict] = []
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
    ) -> list[dict]:
        if not history:
            history = History()
        formatted_history = []
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

