# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from src.domains.dto import ToolCallDTO, ToolResultDTO, ToolDefinitionDTO
from src.domains.exceptions import ToolsDefinitionEmpty
from src.domains.interfaces.tool_registry_interface import IToolRegistry
from src.domains.services.tracer_service import trace_tool
from src.shared.exceptions import ExceptionHandler
from src.shared.constants import ToolContext
from src.shared.logger import logging


class ToolOrchestrationService:
    """Domain service for orchestrating tool execution"""

    def __init__(
        self,
        tool_registry: IToolRegistry,
    ):
        self.__tool_registry = tool_registry

    def get_sentinel_tool(self, context: ToolContext) -> ToolDefinitionDTO:
        assert isinstance(context, ToolContext)
        tool_list = self.get_available_tools([context])
        assert (
            len(tool_list) == 1
        )  # sentinel tool must be the only tool definition of the context
        return tool_list[0]

    def get_available_tools(
        self, contexts: list[ToolContext]
    ) -> list[ToolDefinitionDTO]:
        """
        Get available tools for a list of contexts

        Args:
            contexts: The contexts list to filter tools by

        Returns:
            Aggregate list of tool definitions in LLM-compatible format
        """
        tools_context: list[ToolDefinitionDTO] = []
        for ctx in contexts:
            tools_context.extend(self.__tool_registry.get_available_tools(ctx))
        if not tools_context:
            raise ToolsDefinitionEmpty(
                message=f"The list of tools definition for contexts={contexts} cannot be empty",
                error_code=400,
            )
        return tools_context

    async def execute_tool_calls(
        self, tool_calls: list[ToolCallDTO]
    ) -> list[ToolResultDTO]:
        """
        Execute multiple tool calls sequentially

        Args:
            tool_calls: list of tool calls to execute

        Returns:
            list of tool execution results
        """
        results = []
        for tool_call in tool_calls:
            try:
                results.append(await self.__execute_single_tool(tool_call=tool_call))
            except ExceptionHandler as e:
                error_result = ToolResultDTO(
                    name=tool_call.name,
                    tool_call_id=tool_call.id,
                    success=False,
                    result=None,
                    error_message=e.message,
                )
                results.append(error_result)
                logging.error(f"Tool {tool_call.name} failed: {str(e)}")

        return results

    @trace_tool
    async def __execute_single_tool(self, tool_call: ToolCallDTO) -> ToolResultDTO:
        """
        Execute a single tool call

        Args:
            tool_call: The tool call to execute

        Returns:
            Tool execution result
        """
        if not self.__tool_registry.validate_tool_parameters(
            tool_call.name, tool_call.parameters
        ):
            raise ExceptionHandler(
                error_code=400, message=f"Invalid parameters for tool {tool_call.name}"
            )

        result = await self.__tool_registry.execute_tool(tool_call)
        if result.success:
            logging.debug(f"Tool {tool_call.name} executed successfully")
        else:
            logging.warning(f"Tool {tool_call.name} failed: {result.error_message}")

        return result
