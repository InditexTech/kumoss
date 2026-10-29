# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import dataclasses
import json

from typing import Any, cast

from litellm import ModelResponse, Usage
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
        notice: str | None = None,
    ) -> LLMResponseDTO:
        if tools and thinking:
            raise InferenceCallThinkingToolError(
                message="Inference cannot be invoked with tools and thinking enabled.",
                error_code=400,
            )

        model_id = self.__model
        max_tokens = self.__max_tokens
        local_history = self.__format_history(history, msg)
        if notice:
            local_history.append({"role": "user", "content": notice})

        if system_prompt:
            local_history.insert(0, {"role": "system", "content": system_prompt})

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
