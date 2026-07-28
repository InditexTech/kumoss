# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from abc import ABC, abstractmethod

from src.domains.entities.history import History
from src.domains.dto import LLMResponseDTO, ToolResultDTO, ToolDefinitionDTO


class ILLMProvider(ABC):
    @abstractmethod
    async def inference(
        self,
        msg: str | list[ToolResultDTO],
        system_prompt: str = None,
        tools: list[ToolDefinitionDTO] = None,
        history: History = None,
        thinking: bool = False,
        web_search: bool = False,
    ) -> LLMResponseDTO:
        """
        Create a message with tool calling capabilities

        Args:
            msg: User message
            system_prompt: System prompt
            tools: List of available tools in LLM-compatible format
            history: Conversation history
            thinking: Whether to enable thinking mode
            web_search: Whether to enable web search

        Returns:
            LLMResponseDTO that may contain tool calls
        """
        pass
