# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from abc import ABC, abstractmethod
from typing import Any

from src.domains.dto import ToolCallDTO, ToolResultDTO, ToolDefinitionDTO
from src.shared.constants import ToolContext


class IToolRegistry(ABC):
    """Interface for managing and executing tools"""

    @abstractmethod
    def get_available_tools(self, context: ToolContext) -> list[ToolDefinitionDTO]:
        """
        Get available tools for a specific context in the format expected by LLM providers

        Args:
            context: The context to filter tools by

        Returns:
            list of tool definitions in LLM-compatible format
        """
        pass

    @abstractmethod
    def get_tool_definition(self, tool_name: str) -> ToolDefinitionDTO:
        """
        Get a specific tool definition by name in LLM-compatible format

        Args:
            tool_name: Name of the tool

        Returns:
            ToolDefinition object
        """
        pass

    @abstractmethod
    async def execute_tool(self, tool_call: ToolCallDTO) -> ToolResultDTO:
        """
        Execute a tool call

        Args:
            tool_call: The tool call to execute

        Returns:
            Result of the tool execution
        """
        pass

    @abstractmethod
    def validate_tool_parameters(
        self, tool_name: str, parameters: dict[str, Any]
    ) -> bool:
        """
        Validate tool parameters against the tool definition

        Args:
            tool_name: Name of the tool
            parameters: Parameters to validate

        Returns:
            True if parameters are valid, False otherwise
        """
        pass
