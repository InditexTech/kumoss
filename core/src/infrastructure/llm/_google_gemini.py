# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import asyncio
from uuid import uuid4
from typing import Any, override

from google.genai import Client
from google.genai import types, errors

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
    InferenceCallThinkingToolError,
    InferenceCallWebSearchTools,
)
from src.shared.constants import LLMProvider
from src.shared.exceptions import ExceptionHandler
from src.shared.logger import logging


class GoogleGemini(ILLMProvider):
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
        self.__thought_signatures: dict[str, bytes] = {}
        self.__client = Client(
            vertexai=True,
            project=api_id,
            location="global",
            http_options=types.HttpOptions(timeout=1000 * 60 * 20),  # 20 mins
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
        response = await self.__client.aio.models.count_tokens(
            model=self.__model.value["model_id"],
            contents=local_history,
            config=types.CountTokensConfig(
                system_instruction=system_prompt,
            ),
        )
        if response.total_tokens:
            return response.total_tokens
        return 0

    @trace_llm
    async def inference(
        self,
        msg: str | list[ToolResultDTO],
        system_prompt: str,
        tools: list[ToolDefinitionDTO] = None,
        history: History = None,
        prefill: str = None,
        thinking: bool = False,
        web_search: bool = False,
    ) -> LLMResponseDTO:
        """
        :param msg: The message to send as user.
        :param system_prompt: System prompt.
        :param history: History list.
        :param prefill: Prefill assistant response.
        :param thinking: Enable extended thinking.
        :param web_search: Enable Google Search grounding.
        :return: Response dict.
        """
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
        local_history = self.__format_history(history, msg)
        if prefill:
            local_history.append(
                types.Content(role="model", parts=[types.Part.from_text(text=prefill)]),
            )

        if web_search:
            tools_config = [types.Tool(google_search=types.GoogleSearch())]
            tool_config = None
        elif tools:
            tools_config = [
                types.Tool(function_declarations=self.__format_tools(tools))
            ]
            tool_config = types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(
                    mode=types.FunctionCallingConfigMode.ANY,
                ),
            )
        else:
            tools_config = None
            tool_config = types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(
                    mode=types.FunctionCallingConfigMode.ANY,
                ),
            )

        async def generate_inference():
            for i in range(4):
                try:
                    return await self.__client.aio.models.generate_content(
                        model=self.__model.value["model_id"],
                        contents=local_history,
                        config=types.GenerateContentConfig(
                            system_instruction=system_prompt,
                            temperature=self.__temperature,
                            max_output_tokens=self.__model.value["max_output_tokens"],
                            thinking_config=types.ThinkingConfig(
                                include_thoughts=thinking,
                            ),
                            safety_settings=[
                                types.SafetySetting(
                                    threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH,
                                    category=t,
                                )
                                for t in types.HarmCategory
                            ],
                            tools=tools_config,
                            tool_config=tool_config,
                        ),
                    )
                except errors.ClientError as e:
                    logging.error(f"google_gemini client error: {e.message}")
                    logging.info(f" retry no {i + 1}/4 in 30 seconds...")
                    await asyncio.sleep(30)
                except errors.ServerError as e:
                    logging.error(f"google_gemini server error: {e.message}")
                    raise ExceptionHandler(
                        message="Google Gemini server exception. Contact with the Data Devops team.",
                        error_code=e.code,
                    )

        response: types.GenerateContentResponse | None = await generate_inference()
        assert isinstance(response, types.GenerateContentResponse)
        parts: list[types.Part] = response.candidates[0].content.parts
        content: str = parts[1].text if thinking else parts[0].text

        response_dto = LLMResponseDTO(
            text=content,
            metadata=LLMMetadata(
                finish_reason=self.__map_stop_reason(
                    response.candidates[0].finish_reason.value
                    if response.candidates
                    else ""
                ),
                model=response.model_version,
                input_tokens=response.usage_metadata.prompt_token_count,
                output_tokens=response.usage_metadata.candidates_token_count,
            ),
            tool_calls=[
                ToolCallDTO(
                    id=part.function_call.id if part.function_call.id else uuid4().hex,
                    name=part.function_call.name,  # TODO
                    parameters=part.function_call.args,
                )
                for part in parts
            ]
            if parts[0].function_call
            else [],
            thinking=parts[0].text if thinking else None,
        )
        for tc in response_dto.tool_calls:
            self.__thought_signatures[tc.id] = parts[0].thought_signature
        return response_dto

    def __format_tools(
        self, tools: list[ToolDefinitionDTO]
    ) -> list[types.FunctionDeclaration]:
        output: list[types.FunctionDeclaration] = []
        for t in tools:
            output.append(
                types.FunctionDeclaration(
                    name=t.name,
                    description=t.description,
                    parameters=t.parameters,
                )
            )
        return output

    def __format_tool_calls(
        self, tool_calls: list[ToolCallDTO]
    ) -> list[types.FunctionCall]:
        output: list[types.FunctionCall] = []
        for call in tool_calls:
            output.append(
                types.Part(
                    function_call=types.FunctionCall(
                        args=call.parameters,
                        name=call.name,
                    ),
                    thought_signature=self.__thought_signatures[call.id],
                )
            )
        return output

    def __format_tool_results(
        self, tool_results: list[ToolResultDTO]
    ) -> list[dict[str, types.FunctionResponse]]:
        output: list[dict[str, types.FunctionResponse]] = []
        for tool in tool_results:
            format_tool = types.Part(
                function_response=types.FunctionResponse(
                    name=tool.name,
                    response={
                        "response": tool.result if tool.success else tool.error_message
                    },
                ),
                thought_signature=self.__thought_signatures[tool.tool_call_id],
            )
            output.append(format_tool)
        return output

    def __format_history(
        self, history: History, last_usr_msg: str | list[ToolResultDTO]
    ) -> list[dict[str, str | types.FunctionCall | types.FunctionResponse]]:
        if not history:
            history = History()
        formatted_history = []
        for turn in history:
            if turn.user:
                formatted_history.append(
                    types.Content(
                        role="user",
                        parts=[types.Part.from_text(text=turn.user)]
                        if isinstance(turn.user, str)
                        else self.__format_tool_results(turn.user),
                    )
                )
            if turn.assistant:
                if isinstance(turn.assistant, str):
                    content = [types.Part.from_text(text=turn.assistant)]
                else:
                    content = self.__format_tool_calls(turn.assistant)
                formatted_history.append(
                    types.Content(
                        role="model",
                        parts=content,
                    )
                )
        formatted_history.append(
            types.Content(
                role="user",
                parts=[types.Part.from_text(text=last_usr_msg)]
                if isinstance(last_usr_msg, str)
                else self.__format_tool_results(last_usr_msg),
            )
        )
        return formatted_history

    @staticmethod
    def __map_stop_reason(reason: str):
        mapped_reason = {
            "STOP": "end_turn",
            "MAX_TOKENS": "max_tokens",
        }.get(reason)
        if not mapped_reason:
            raise ExceptionHandler(
                message=f"Unmapped finish reason {reason}",
                error_code=500,
            )
        return mapped_reason
