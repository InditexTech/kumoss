# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

# pyright: reportArgumentType=false, reportOptionalMemberAccess=false
# import asyncio
import json

# from dataclasses import dataclass, asdict
from typing import Any  # ,override

import litellm
# from litellm import acompletion

from src.domains.interfaces.llm_interface import ILLMProvider
from src.domains.dto import (
    LLMResponseDTO,
    # LLMMetadata,
    ToolCallDTO,
    ToolResultDTO,
    ToolDefinitionDTO,
)
from src.domains.entities.history import History
from src.domains.services.tracer_service import trace_llm
from src.infrastructure.exceptions import (
    # InferenceCallAPIError,
    InferenceCallThinkingToolError,
    InferenceCallWebSearchTools,
)
from src.shared.constants import LLMProvider
# from src.shared.logger import logging


class LiteLLMAdapter(ILLMProvider):
    def __init__(
        self,
        model: LLMProvider,
        temperature: float,
        provider_kwargs: dict[str, Any] = None,
    ) -> None:
        """LiteLLM-based LLM adapter for unified multi-provider inference.

        Wraps litellm.acompletion to route requests to any supported provider
        (Vertex AI, Bedrock, OpenAI, Azure, Azure AI, Gemini) using OpenAI-
        compatible formatting. The inference method is pending implementation;
        helper methods for tool formatting, history construction, and stop
        reason mapping are ready.
        """
        self.__model = model
        self.__provider = model.value["model_id"].split("/")[0]
        self.__temperature = temperature
        self.__provider_kwargs = provider_kwargs or {}

        # Set the global drop_params flag to True to avoid sending unnecessary parameters
        litellm.drop_params = True

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
        if web_search and tools:
            raise InferenceCallWebSearchTools(
                message="Inference cannot be invoked with tools and web search enabled.",
                error_code=400,
            )
        if web_search and thinking:
            raise InferenceCallThinkingToolError(
                message="Inference cannot be invoked with thinking and web search enabled.",
                error_code=400,
            )

        # local_history = self.__format_history(history, msg)

        # async def generate_inference() -> Message | None:
        #     for i in range(4):
        #         try:
        #             return await self.__client.messages.create(
        #                 model=self.__model.value["model_id"],
        #                 messages=local_history,
        #                 max_tokens=self.__model.value["max_tokens"],
        #                 system=system_prompt if system_prompt else NOT_GIVEN,
        #                 temperature=1.0 if thinking else self.__temperature,
        #                 thinking=ThinkingConfigEnabledParam(
        #                     budget_tokens=int(
        #                         int(self.__model.value["max_tokens"]) * 0.75
        #                     ),
        #                     type="enabled",
        #                 )
        #                 if thinking
        #                 else NOT_GIVEN,
        #                 tool_choice=ToolChoiceAnyParam(
        #                     type="any", disable_parallel_tool_use=False
        #                 )
        #                 if tools
        #                 else NOT_GIVEN,
        #                 tools=self.__format_tools(tools) if tools else NOT_GIVEN,
        #             )
        #         # https://docs.anthropic.com/en/api/errors
        #         except RateLimitError as e:
        #             logging.error(f"Anthropic Vertex rate limit error: {e.message}")
        #         except APIError as e:
        #             logging.error(f"Anthropic Vertex API error: {e.message}")
        #         logging.info(f" retry no {i + 1}/4 in 30 seconds...")
        #         await asyncio.sleep(30)
        #         if i == 3:
        #             raise InferenceCallAPIError(
        #                 message=f"Inference calls to {self.__model.name} have been exhausted.",
        #                 error_code=502,
        #             )

        # response = await generate_inference()

        # return LLMResponseDTO(
        #     text=response.content[1 if thinking else 0].text
        #     if isinstance(response.content[1 if thinking else 0], TextBlock)
        #     else "",
        #     metadata=LLMMetadata(
        #         finish_reason=self.__map_stop_reason(response.stop_reason),
        #         model=response.model,
        #         input_tokens=response.usage.input_tokens,
        #         output_tokens=response.usage.output_tokens,
        #     ),
        #     tool_calls=[
        #         ToolCallDTO(
        #             id=call.id,
        #             name=call.name,
        #             parameters=call.input,
        #         )
        #         for call in response.content
        #         if isinstance(call, ToolUseBlock)
        #     ],
        #     thinking=response.content[0].thinking if thinking else None,
        # )
        pass

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
