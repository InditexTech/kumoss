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
        system_prompt: str | None = None,
        tools: list[ToolDefinitionDTO] | None = None,
        history: History = None,
        thinking: bool = False,
        web_search: bool = False,
        notice: str | None = None,
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
            notice: Harness note sent as a user message after msg, for this
                call only (it is not part of the history)

        Returns:
            LLMResponseDTO that may contain tool calls
        """
        pass
