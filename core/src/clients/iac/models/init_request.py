# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Self, TypeVar

from attrs import define as _attrs_define

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.provider_scope import ProviderScope


T = TypeVar("T", bound="InitRequest")


@_attrs_define
class InitRequest:
    """
    Attributes:
        workspace_path (str): Absolute filesystem path to the Terraform workspace as visible
            to the implementation. For the OSS docker-compose deployment,
            this is a path on the shared volume mounted into both the
            core and the IaC service.
        scopes (list[ProviderScope] | Unset): Scope of each provider the command should run against, at
            most one entry per `provider` (a duplicate is rejected with
            `422`). Optional; an empty list injects nothing. See "Scope
            injection".
    """

    workspace_path: str
    scopes: list[ProviderScope] | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        workspace_path = self.workspace_path

        scopes: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.scopes, Unset):
            scopes = []
            for scopes_item_data in self.scopes:
                scopes_item = scopes_item_data.to_dict()
                scopes.append(scopes_item)

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "workspace_path": workspace_path,
            }
        )
        if scopes is not UNSET:
            field_dict["scopes"] = scopes

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.provider_scope import ProviderScope

        d = dict(src_dict)
        workspace_path = d.pop("workspace_path")

        _scopes = d.pop("scopes", UNSET)
        scopes: list[ProviderScope] | Unset = UNSET
        if _scopes is not UNSET:
            scopes = []
            for scopes_item_data in _scopes:
                scopes_item = ProviderScope.from_dict(scopes_item_data)

                scopes.append(scopes_item)

        init_request = cls(
            workspace_path=workspace_path,
            scopes=scopes,
        )

        return init_request
