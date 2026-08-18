# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from abc import ABC, abstractmethod
from typing import Any

from src.domains.entities.history import History
from src.domains.dto import LLMResponseDTO, ToolResultDTO, ToolDefinitionDTO
from src.shared.constants import LLMProvider


class ILLMProvider(ABC):
    @property
    @abstractmethod
    def provider(self) -> LLMProvider:
        """Returns the concrete class provider"""
        pass

    @property
    @abstractmethod
    def client(self) -> Any:
        """Returns the intantiated class client"""
        pass

    @abstractmethod
    async def inference(
        self,
        msg: str | list[ToolResultDTO],
        system_prompt: str = None,
        tools: list[ToolDefinitionDTO] = None,
        history: History = None,
        prefill: str = None,
        thinking: bool = False,
    ) -> LLMResponseDTO:
        """
        Create a message with tool calling capabilities

        Args:
            msg: User message
            system_prompt: System prompt
            tools: List of available tools in LLM-compatible format
            history: Conversation history
            prefill: Response prefill
            thinking: Whether to enable thinking mode

        Returns:
            LLMResponseDTO that may contain tool calls
        """
        pass

    @abstractmethod
    async def count_tokens(
        self,
        msg: str,
        system_prompt: str = None,
        history: History = None,
        thinking: bool = False,
        tools: list[dict[str, Any]] = None,
    ) -> int:
        pass
