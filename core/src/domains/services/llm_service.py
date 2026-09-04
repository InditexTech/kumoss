# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

# pyright: reportArgumentType=false, reportReturnType=false

from src.domains.entities.history import History
from src.domains.interfaces.llm_interface import ILLMProvider
from src.domains.services.tool_service import ToolOrchestrationService
from src.domains.services.tracer_service import trace_chain
from src.domains.dto import (
    ToolResultDTO,
    PromptTemplateDTO,
    ToolDefinitionDTO,
    LLMResponseDTO,
)
from src.domains.exceptions import (
    SentinelToolError,
    UnhandledInferenceFinishReason,
    ToolExecutionsExceeded,
)
from src.shared.config import system_config
from src.shared.constants import PromptsLibrary
from src.shared.logger import logging


class LLMOrchestrationService:
    def __init__(
        self,
        main_llm_provider: ILLMProvider,
        small_llm_provider: ILLMProvider,
        tool_service: ToolOrchestrationService | None = None,
    ):
        self.__main_llm = main_llm_provider
        self.__small_llm = small_llm_provider
        self.__tool_svc = tool_service

    @trace_chain
    async def generate_text(
        self,
        query: str,
        prompt: PromptTemplateDTO = None,
        history: History | None = None,
        thinking: bool = False,
    ) -> str:
        """
        Generate a plain text response from the LLM without tool execution capabilities.

        This method sends a query to the LLM and returns the generated text response directly.
        Unlike the generate() method, this method does not support tool execution and is
        designed for scenarios where only text generation is needed, such as simple Q&A,
        content generation, or text processing tasks.

        :param query: (str): The input message or question to send to the LLM.
        :param prompt: (PromptTemplateDTO, optional): System prompt template containing instructions
                for the LLM behavior. If None, no system prompt is used. Defaults to None.
        :param history: (History, optional): Conversation history to maintain context across
                multiple interactions. If None, starts with empty history. Defaults to None.
        :param thinking: (bool, optional): Whether to enable thinking mode for the LLM,
                which may affect response generation and reasoning process. Defaults to False.


        :return: str: The generated text response from the LLM.

        Note:
            - This method does not modify the original history object
            - No tool execution is performed, making it faster for simple text generation
            - Ideal for use cases that require only textual responses without actions
        """
        response = await self.__small_llm.inference(
            msg=query,
            system_prompt=prompt.prompt if prompt else None,
            history=history,
            thinking=thinking,
        )
        return response.text

    @trace_chain
    async def generate(
        self,
        query: str,
        tools: list[ToolDefinitionDTO],
        sentinel_tool: ToolDefinitionDTO | None = None,
        prompt: PromptTemplateDTO = None,
        history: History = None,
    ) -> ToolResultDTO:
        """
        Generate a response from the LLM with tool execution capabilities.

        This method orchestrates the interaction between the LLM and available tools. It sends
        a query to the LLM and handles tool execution when the model decides to use tools.
        For multi-tool scenarios, it continues the conversation loop until a sentinel tool
        ("task_complete") is executed, indicating the task is finished.

        :param query: (str): The input message or question to send to the LLM.
        :param tools: (list[ToolDefinitionDTO], optional): List of tool definitions that the LLM
                can choose to execute. If None, no tools are available. Defaults to None.
        :param sentinel_tool: (ToolDefinitionDTO, optional): Special tool that signals task completion
                in multi-tool scenarios. When this tool is executed, the conversation loop terminates.
                Required for multi-tool workflows but not needed for single tool execution.
                Commonly used with "task_complete" or similar completion indicators. Defaults to None.
        :param prompt: (PromptTemplateDTO, optional): System prompt template containing instructions
                for the LLM behavior. If None, no system prompt is used. Defaults to None.
        :param history: (History, optional): (read only) Conversation history to maintain context across
                multiple interactions. If None, starts with empty history. Defaults to None.
        :param thinking: (bool, optional): Whether to enable thinking mode for the LLM,
                which may affect response generation. Defaults to False.

        :return: ToolResultDTO: The last toolResultDTO.

        Note:
            - The method creates a deep copy of the history to avoid modifying the original
            - For single tool execution, returns immediately after tool execution
            - For multi-tool scenarios, continues until "task_complete" sentinel is executed
            - All tool executions and responses are automatically added to the conversation history
        """
        assert self.__tool_svc is not None
        assert len(tools) >= 1
        if len(tools) > 1 and sentinel_tool is None:
            raise ValueError(
                "sentinel_tool is required when multiple tools are provided"
            )

        local_tools = tools.copy()
        if sentinel_tool is None:
            sentinel_tool = local_tools[0]
        else:
            assert isinstance(sentinel_tool, ToolDefinitionDTO)
            local_tools.append(sentinel_tool)

        local_history = history.deepcopy() if history else History()

        tools_result: str | list[ToolResultDTO] = query
        total_executions = 0
        while not self.__sentinel_executed(sentinel_tool, tools_result, local_tools):
            if (
                total_executions
                == system_config.orchestration.max_tool_agent_executions
            ):
                raise ToolExecutionsExceeded(
                    message="The total number of tool executions in this chain has reached the limit. Limit="
                    + f"{system_config.orchestration.max_tool_agent_executions}",
                    error_code=500,
                )
            response: LLMResponseDTO = await self.__select_model(prompt).inference(
                msg=tools_result,
                tools=local_tools,
                system_prompt=prompt.prompt,
                history=local_history,
            )
            if response.metadata.finish_reason not in ["tool_use", "end_turn"]:
                raise UnhandledInferenceFinishReason(
                    message=f"Error: unexpected finish reason - {response.metadata.finish_reason}",
                    error_code=500,
                )
            local_history.append_turn(tools_result, response.tool_calls)
            tools_result = await self.__tool_svc.execute_tool_calls(response.tool_calls)
            if not tools_result:
                logging.warning(f"Error inference - no tool response: {response}")
                tools_result = "you MUST use a tool"
            total_executions += 1

        return tools_result[-1]

    def __select_model(self, prompt: PromptTemplateDTO) -> ILLMProvider:
        if prompt.type.name in [
            PromptsLibrary.IAC_GENERATOR.name,
            PromptsLibrary.TARGET_GENERATOR.name,
            PromptsLibrary.REPORT_GENERATOR.name,
        ]:
            return self.__main_llm
        return self.__small_llm

    def __sentinel_executed(
        self,
        sentinel_tool: ToolDefinitionDTO,
        tool_results: list[ToolResultDTO] | str,
        tools: list[ToolDefinitionDTO],
    ) -> bool:
        if isinstance(tool_results, str):
            return False
        if sentinel_tool.name not in [tool.name for tool in tools]:
            raise SentinelToolError(
                message=f"Sentinel tool '{sentinel_tool.name}' is not included in the list of tools definitions",
                error_code=404,
            )
        for tool in tool_results:
            if tool.name == sentinel_tool.name and tool.result:
                return True
        return False
