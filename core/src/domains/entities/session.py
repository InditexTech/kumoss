# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

# pyright: reportAttributeAccessIssue=false
from pathlib import Path
from typing import override
from uuid import UUID

from src.domains.entities.history import History
from src.domains.value_objects.manifest import TerraformInputs
from src.domains.value_objects.provider_scope import ProviderScope
from src.shared.constants import OperationType


class SessionContext:
    def __init__(
        self,
        id: UUID,
        user_id: str,
        round_id: int,
        repo_uri: str,
        providers: tuple[ProviderScope, ...],
        branch_name: str,
        root_module_path: str,
        operation_type: OperationType,
        history: list[dict[str, str]],
        chat_history: list[dict[str, str]],
        user_queries: list[str] | None = None,
        project_identifier: str | None = None,
    ):
        self.__id = id
        self.__user_id = user_id
        self.__round_id = round_id
        self.__repo_uri = repo_uri
        self.__providers = tuple(providers)
        self.__branch_name = branch_name
        self.__root_module_path = root_module_path
        self.__project_identifier = project_identifier
        self.__operation = operation_type
        self.__history: History = History(history, user_queries)
        self.__chat_history: History = History(chat_history)
        self.__call_dir: Path | None = None
        self.__terraform_inputs: TerraformInputs | None = None

    @property
    def id(self) -> UUID:
        return self.__id

    @property
    def user_id(self) -> str:
        return self.__user_id

    @property
    def round_id(self) -> int:
        return self.__round_id

    def set_round(self, rid: int) -> None:
        self.__round_id = rid

    @property
    def repo_uri(self) -> str:
        return self.__repo_uri

    @property
    def providers(self) -> tuple[ProviderScope, ...]:
        """The Terraform providers of the session's root module, with their scopes.

        Empty until the first call has set the root module up (they come
        from its manifest, not from the request).
        """
        return self.__providers

    def set_providers(self, providers: tuple[ProviderScope, ...]) -> None:
        self.__providers = tuple(providers)

    @property
    def provider_types(self) -> tuple[str, ...]:
        return tuple(p.provider for p in self.__providers)

    @property
    def scopes(self) -> tuple[ProviderScope, ...]:
        """The pairs that carry a scope: what authorization and injection act on."""
        return tuple(p for p in self.__providers if p.scope_id)

    @property
    def branch_name(self) -> str:
        return self.__branch_name

    @property
    def root_module_path(self) -> str:
        return self.__root_module_path

    @property
    def project_identifier(self) -> str | None:
        """What the user named the repository, when not by ``repo_uri`` itself.

        Checked against the mapping service when the session was created;
        the IaC service may pick the credentials commands run with by it.
        """
        return self.__project_identifier

    @property
    def operation(self) -> OperationType:
        return self.__operation

    @property
    def history(self) -> History:
        """Internal record fed to the LLM. Not part of any public contract."""
        return self.__history

    @property
    def chat_history(self) -> History:
        """User-facing conversation: one turn per finished round."""
        return self.__chat_history

    @property
    def call_dir(self) -> Path:
        assert self.__call_dir is not None
        return self.__call_dir

    def set_call_dir(self, path: Path) -> None:
        self.__call_dir = path

    @property
    def terraform_inputs(self) -> TerraformInputs | None:
        """The root module's configured variables for this call; None until loaded.

        Runtime only, never persisted: values may include secrets.
        """
        return self.__terraform_inputs

    def set_terraform_inputs(self, inputs: TerraformInputs) -> None:
        self.__terraform_inputs = inputs

    @override
    def __str__(self) -> str:
        return f"session: {self.__id}"
