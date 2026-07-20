# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

# pyright: reportAttributeAccessIssue=false
from pathlib import Path
from typing import override, Any
from uuid import UUID
from datetime import datetime

from src.domains.entities.history import History
from src.shared.constants import ReportType, TerraformProvider


class SessionContext:
    def __init__(
        self,
        id: UUID,
        user_id: str,
        repo_uri: str,
        scope_id: str,
        terraform_prv: TerraformProvider,
        branch_name: str,
        iac_path: str,
        created_at: datetime,
        updated_at: datetime,
        history: list[dict[str, str]],
        is_blocked: bool,
    ):
        self.__id = id
        self.__user_id = user_id
        self.__repo_uri = repo_uri
        self.__scope_id = scope_id
        self.__terraform_prv = terraform_prv
        self.__branch_name = branch_name
        self.__iac_path = iac_path
        self.__history: History = History(history)
        self.__is_blocked: bool = is_blocked
        self.__created_at: datetime = created_at
        self.__updated_at: datetime = updated_at
        self.__artifacts: list[
            dict[str, Any]
        ]  # TODO: implement entity and services, interfaces...
        self.__call_dir: Path = None
        self.__report_type = None

    @property
    def id(self) -> UUID:
        return self.__id

    @property
    def user_id(self) -> str:
        return self.__user_id

    @property
    def repo_uri(self) -> str:
        return self.__repo_uri

    @property
    def scope_id(self) -> str:
        return self.__scope_id

    @property
    def terraform_prv(self) -> TerraformProvider:
        return self.__terraform_prv

    @property
    def report_type(self) -> ReportType:
        assert self.__report_type is not None
        return self.__report_type

    def set_report_type(self, type: ReportType) -> None:
        self.__report_type = type

    @property
    def branch_name(self) -> str:
        return self.__branch_name

    @property
    def iac_path(self) -> str:
        return self.__iac_path

    @property
    def history(self) -> History:
        return self.__history

    @property
    def call_dir(self) -> Path:
        assert self.__call_dir is not None
        return self.__call_dir

    def set_call_dir(self, path: Path) -> None:
        self.__call_dir = path

    @property
    def is_blocked(self) -> bool:
        return self.__is_blocked

    @override
    def __str__(self) -> str:
        return f"session: {self.__id} (blocked={self.__is_blocked})"
