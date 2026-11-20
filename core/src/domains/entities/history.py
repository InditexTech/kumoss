# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import copy
from collections.abc import Iterable, Iterator
from typing import override

from src.domains.dto import ToolCallDTO, ToolResultDTO
from src.domains.entities._turn import Turn
from src.domains.exceptions import HistoryLastTurnError
from src.shared.logger import logging


class History(Iterable[Turn]):
    """
    Class for storing the history of a conversation.
    """

    def __init__(
        self,
        initial_state: list[dict[str, str]] | None = None,
        user_queries: list[str] | None = None,
    ) -> None:
        self.__history: list[Turn] = []
        self.__user_queries: list[str] = list(user_queries or [])
        if initial_state:
            for turn in initial_state:
                self.append_turn(
                    user_msg=turn.get("user"), assistant_msg=turn.get("assistant")
                )

    @override
    def __iter__(self) -> Iterator[Turn]:
        yield from self.__history

    def __len__(self):
        return len(self.__history)

    @override
    def __str__(self) -> str:
        return "".join([str(turn) for turn in self.__history])

    def deepcopy(self):
        return copy.deepcopy(self)

    @property
    def user_queries(self) -> tuple[str, ...]:
        """Every query that opened a round of the session, oldest first."""
        return tuple(self.__user_queries)

    def add_user_query(self, query: str) -> None:
        self.__user_queries.append(query)

    def reset(self):
        logging.warning("History has been reset.")
        self.__history = []

    def get_last_turn(self) -> Turn:
        if not self.__history:
            raise HistoryLastTurnError(
                message="History is empty. Last turn cannot be retrieved.",
                error_code=500,
            )
        return self.__history[-1]

    def append_turn(
        self,
        user_msg: str | list[ToolResultDTO],
        assistant_msg: str | list[ToolCallDTO],
    ) -> None:
        """
        Append a turn to the history.
        :param user_msg: The user message.
        :param assistant_msg: The assistant message.
        :return: None
        """
        if not user_msg or not assistant_msg:
            logging.warning("append_turn empty user or assistant msg, turn skipped")
            return
        self.__history.append(
            Turn(
                user=user_msg,
                assistant=assistant_msg,
                turn_id=str(len(self.__history)),
            )
        )

    def serialize(self) -> list[dict[str, str]]:
        """
        serialize returns the internal obj representation in a standard format
        """
        return [
            {"user": str(turn.user), "assistant": str(turn.assistant)}
            for turn in self.__history
        ]
