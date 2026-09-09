# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import copy
from typing import override
from collections.abc import Iterator, Iterable

from src.domains.entities._turn import Turn
from src.domains.dto import ToolResultDTO, ToolCallDTO
from src.domains.exceptions import HistoryFirstTurnError, HistoryLastTurnError
from src.shared.logger import logging


class History(Iterable[Turn]):  # for the type checker
    """
    Class for storing the history of a conversation.
    """

    def __init__(self, initial_state: list[dict[str, str]] = None) -> None:
        self.__history: list[Turn] = []
        if initial_state:
            for turn in initial_state:
                self.append_turn(
                    user_msg=turn.get("user"), assistant_msg=turn.get("assistant")
                )

    @override
    def __iter__(self) -> Iterator[Turn]:
        for turn in self.__history:
            yield turn

    def __len__(self):
        return len(self.__history)

    @override
    def __str__(self) -> str:
        return "".join([str(turn) for turn in self.__history])

    def deepcopy(self):
        return copy.deepcopy(self)

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

    def get_first_turn(self) -> Turn:
        if not self.__history:
            raise HistoryFirstTurnError(
                message="History is empty. First turn cannot be retrieved.",
                error_code=500,
            )
        return self.__history[0]

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


if __name__ == "__main__":
    msgs = History(
        [
            {"user": "hey", "assistant": "how you doing mate"},
            {"user": "i'm doin' o right", "assistant": "good to know"},
        ]
    )

    for idx, msg in enumerate(msgs):
        print(idx, msg)
