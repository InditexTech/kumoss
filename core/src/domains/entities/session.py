# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

# pyright: reportAttributeAccessIssue=false
from dataclasses import dataclass
from uuid import UUID
from asyncio import Queue, QueueEmpty

from src.domains.dto import SessionPayloadDTO
from src.shared.constants import SessionStatus
from src.shared.logger import logging

# TODO: remove in-memory sessions
_SESSIONS: dict[str, "Session"] = {}


@dataclass
class _Status:
    status: SessionStatus
    message: str


class Session:
    def __init__(
        self,
        id: UUID,
        status: _Status,
    ):
        self.__id = id
        self.__status: Queue[_Status] = Queue()
        self.__last_status: _Status = _Status(
            status=SessionStatus.STARTED,
            message=f"Session with ID {str(id)[:4]} started.",
        )
        self.__validation_id: str = ""
        self.__payload: SessionPayloadDTO = None
        _SESSIONS[id.hex] = self

    @property
    def id(self):
        return str(self.__id)

    @property
    def status(self) -> _Status:
        try:
            curr_status = self.__status.get_nowait()
            self.__last_status = curr_status
            return curr_status
        except QueueEmpty:
            return self.__last_status

    def set_status(self, status: SessionStatus, message: str):
        self.__status.put_nowait(_Status(status=status, message=message))

    @property
    def validation_id(self):
        return self.__validation_id

    def set_validation_id(self, id: str):
        self.__validation_id = id

    @property
    def payload(self):
        return self.__payload

    def set_payload(self, payload: SessionPayloadDTO):
        self.__payload = payload

    def delete(self) -> None:
        del _SESSIONS[self.__id.hex]
        logging.warning(f"Session successfully deleted. id={self.id}")
        logging.info(f"Current sessions number={len(_SESSIONS)}")

    def __str__(self) -> str:
        return f"session: {self.__id}\nstate: {self.__status}"


def get_session(id: UUID) -> Session | None:
    return _SESSIONS.get(id.hex)
