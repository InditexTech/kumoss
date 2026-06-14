# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

# pyright: reportArgumentType=false, reportOptionalMemberAccess=false
import asyncio

from dataclasses import dataclass, asdict
from typing import Any, override

from anthropic.types import (
    ThinkingConfigEnabledParam,
    ToolChoiceAnyParam,
    ToolUseBlock,
    TextBlock,
)
from anthropic import AsyncAnthropicVertex, NOT_GIVEN, APIError, RateLimitError
from anthropic.types.message import Message

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
from src.shared.constants import LLMProvider
from src.shared.logger import logging


@dataclass
class AnthropicToolResult:
    tool_use_id: str
    content: str
    type: str = "tool_result"


@dataclass
class AnthropicToolCall:
    id: str
    name: str
    input: dict[str, Any]
    type: str = "tool_use"


class AnthropicVertex(ILLMProvider):
    def __init__(
        self,
        model: LLMProvider,
        api_id: str,
        temperature: float,
    ) -> None:
        """
        Anthropic Vertex LlmBase initialization.
        :param model: Claude model LLM enum.
        :param api_id: GCP project id.
        """
        self.__model = model
        self.__temperature = temperature
        self.__client = AsyncAnthropicVertex(
            project_id=api_id,
            region=model.value["region"],
            timeout=120,
        )

    @property
    @override
    def provider(self) -> LLMProvider:
        return self.__model

    @property
    @override
    def client(self) -> Any:
        return self.__client

    @override
    async def count_tokens(
        self,
        msg: str,
        system_prompt: str = None,
        history: History = None,
        thinking: bool = False,
        tools: list[dict[str, Any]] = None,
    ) -> int:
        local_history = self.__format_history(history, msg)
        response = await self.__client.messages.count_tokens(
            model=self.__model.value["model_id"],
            messages=local_history,
            system=system_prompt if system_prompt else NOT_GIVEN,
            thinking=ThinkingConfigEnabledParam(
                budget_tokens=int(int(self.__model.value["max_output_tokens"]) * 0.75),
                type="enabled",
            )
            if thinking
            else NOT_GIVEN,
        )
        return response.input_tokens

    @trace_llm
    async def inference(
        self,
        msg: str | list[ToolResultDTO],
        system_prompt: str,
        tools: list[ToolDefinitionDTO] = None,
        history: History = None,
        prefill: str = None,
        thinking: bool = False,
    ) -> LLMResponseDTO:
        if tools and thinking:
            raise InferenceCallThinkingToolError(
                message="Inference cannot be invoked with tools and thinking enabled.",
                error_code=400,
            )
        local_history = self.__format_history(history, msg)
        if prefill:
            local_history.append({"role": "assistant", "content": prefill})

        async def generate_inference() -> Message | None:
            for i in range(4):
                try:
                    return await self.__client.messages.create(
                        model=self.__model.value["model_id"],
                        messages=local_history,
                        max_tokens=self.__model.value["max_output_tokens"],
                        system=system_prompt if system_prompt else NOT_GIVEN,
                        temperature=1.0 if thinking else self.__temperature,
                        thinking=ThinkingConfigEnabledParam(
                            budget_tokens=int(
                                int(self.__model.value["max_output_tokens"]) * 0.75
                            ),
                            type="enabled",
                        )
                        if thinking
                        else NOT_GIVEN,
                        tool_choice=ToolChoiceAnyParam(
                            type="any", disable_parallel_tool_use=False
                        )
                        if tools
                        else NOT_GIVEN,
                        tools=self.__format_tools(tools) if tools else NOT_GIVEN,
                    )
                # https://docs.anthropic.com/en/api/errors
                except RateLimitError as e:
                    logging.error(f"Anthropic Vertex rate limit error: {e.message}")
                except APIError as e:
                    logging.error(f"Anthropic Vertex API error: {e.message}")
                logging.info(f" retry no {i + 1}/4 in 30 seconds...")
                await asyncio.sleep(30)
                if i == 3:
                    raise InferenceCallAPIError(
                        message=f"Inference calls to {self.__model.name} have been exhausted.",
                        error_code=502,
                    )

        response = await generate_inference()

        return LLMResponseDTO(
            text=response.content[1 if thinking else 0].text
            if isinstance(response.content[1 if thinking else 0], TextBlock)
            else "",
            metadata=LLMMetadata(
                finish_reason=self.__map_stop_reason(response.stop_reason),
                model=response.model,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
            ),
            tool_calls=[
                ToolCallDTO(
                    id=call.id,
                    name=call.name,
                    parameters=call.input,
                )
                for call in response.content
                if isinstance(call, ToolUseBlock)
            ],
            thinking=response.content[0].thinking if thinking else None,
        )

    def __format_tools(self, tools: list[ToolDefinitionDTO]) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []

        for t in tools:
            output.append(
                {
                    "name": t.name,
                    "description": t.description,
                    "input_schema": t.parameters,
                }
            )
        return output

    def __format_tool_results(
        self, tool_results: list[ToolResultDTO]
    ) -> list[dict[str, AnthropicToolResult]]:
        output: list[dict[str, AnthropicToolResult]] = []
        for result in tool_results:
            format_tool = AnthropicToolResult(
                tool_use_id=result.tool_call_id,
                content=str(result.result) if result.success else result.error_message,
            )
            output.append(asdict(format_tool))

        return output

    def __format_tool_calls(
        self, tool_calls: list[ToolCallDTO]
    ) -> list[dict[str, AnthropicToolCall]]:
        output: list[dict[str, AnthropicToolCall]] = []
        for call in tool_calls:
            format_tool = AnthropicToolCall(
                id=call.id,
                name=call.name,
                input=call.parameters,
            )
            output.append(asdict(format_tool))

        return output

    def __format_history(
        self, history: History, last_usr_msg: str | list[ToolResultDTO]
    ) -> list[dict[str, str | AnthropicToolCall | AnthropicToolResult]]:
        if not history:
            history = History()
        formatted_history = []
        for turn in history:
            formatted_history.append(
                {
                    "role": "user",
                    "content": self.__format_tool_results(turn.user)
                    if isinstance(turn.user, list)
                    else turn.user,
                }
            )
            if turn.assistant:
                formatted_history.append(
                    {
                        "role": "assistant",
                        "content": self.__format_tool_calls(turn.assistant)
                        if isinstance(turn.assistant, list)
                        else turn.assistant,
                    }
                )
        formatted_history.append(
            {
                "role": "user",
                "content": self.__format_tool_results(last_usr_msg)
                if isinstance(last_usr_msg, list)
                else last_usr_msg,
            }
        )
        return formatted_history

    def __map_stop_reason(self, reason: str):
        return {
            "end_turn": "end_turn",
            "max_tokens": "max_tokens",
            "stop_sequence": "content_filter",
            "tool_use": "tool_use",
        }.get(reason)
