# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

# pyright: reportAttributeAccessIssue=false
from dataclasses import dataclass
from typing import override, Any
from uuid import UUID
from asyncio import Queue

from src.domains.entities import History
from src.shared.constants import SessionStatus, TemplateProvider


@dataclass
class _Status:
    status: SessionStatus
    message: str


class SessionContext:
    def __init__(
        self,
        id: UUID,
        user_id: str,
        repo_uri: str,
        cloud: TemplateProvider,
        branch_name: str,
        iac_path: str,
        history: list[dict[str, str]] = None,
    ):
        self.__id = id
        self.__user_id = user_id
        self.__status: Queue[_Status] = Queue()
        self.__repo_uri = repo_uri
        self.__cloud = cloud
        self.__branch_name = branch_name
        self.__iac_path = iac_path
        self.__history: History = History(history)
        self.__artifacts: list[
            dict[str, Any]
        ]  # TODO: implement entity and services, interfaces...
        self.set_status(SessionStatus.STARTED, message="Session started")

    @property
    def id(self) -> UUID:
        return self.__id

    @property
    def user_id(self) -> str:
        return self.__user_id

    @property
    def status(self) -> _Status:
        return self.__status.get_nowait()

    def set_status(self, status: SessionStatus, message: str):
        self.__status.put_nowait(_Status(status=status, message=message))

    @property
    def repo_uri(self) -> str:
        return self.__repo_uri

    @property
    def cloud(self) -> TemplateProvider:
        return self.__cloud

    @property
    def branch_name(self) -> str:
        return self.__branch_name

    @property
    def iac_path(self) -> str:
        return self.__iac_path

    @property
    def history(self) -> History:
        return self.__history

    @override
    def __str__(self) -> str:
        return f"session: {self.__id}\nstate: {self.__status}"
