# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from src.domains.dto import ToolResultDTO, ToolCallDTO


class Turn:
    def __init__(
        self,
        user: str | list[ToolResultDTO],
        assistant: str | list[ToolCallDTO],
        turn_id: str = None,
    ) -> None:
        """
        Class for storing a whole turn in a conversation.
        A whole turn is a pair of user and assistant messages.
        :param user: The user message.
        :param assistant: The assistant message.
        :param turn_id: The turn id.
        """
        self.user: str | list[ToolResultDTO] = user
        self.assistant: str | list[ToolCallDTO] = assistant
        self.turn_id: str = turn_id

    def __str__(self) -> str:
        return f"user: {self.user}\nassistant: {self.assistant}\nid: {self.turn_id}"
