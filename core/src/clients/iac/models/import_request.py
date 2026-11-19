# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Self, TypeVar, cast

from attrs import define as _attrs_define

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.provider_scope import ProviderScope
    from ..models.variables import Variables


T = TypeVar("T", bound="ImportRequest")


@_attrs_define
class ImportRequest:
    """
    Attributes:
        workspace_path (str): Absolute filesystem path to the Terraform workspace as visible
            to the implementation. For the OSS docker-compose deployment,
            this is a path on the shared volume mounted into both the
            core and the IaC service.
        address (str): Terraform resource address to import into, e.g.
            `azurerm_resource_group.main`.
        resource_id (str): Provider-specific identifier of the existing cloud resource,
            e.g. an Azure resource ID or an AWS ARN.
        scopes (list[ProviderScope] | Unset): Scope of each provider the command should run against, at
            most one entry per `provider` (a duplicate is rejected with
            `422`). Optional; an empty list injects nothing. See "Scope
            injection".
        var_files (list[str] | Unset): Variable-definition files to pass as `-var-file`, in order.
            Each is a path relative to `workspace_path` made of plain
            segments (no `.`/`..`, no hidden segments, no leading `/`),
            ending in `.tfvars` or `.tfvars.json`. See "Input variables".
        variables (Variables | Unset): Input variable values by name, of any JSON type. Passed after
            `var_files`, so they win over them. May contain secrets: never
            logged, persisted, or written inside the workspace. See
            "Input variables".
    """

    workspace_path: str
    address: str
    resource_id: str
    scopes: list[ProviderScope] | Unset = UNSET
    var_files: list[str] | Unset = UNSET
    variables: Variables | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        workspace_path = self.workspace_path

        address = self.address

        resource_id = self.resource_id

        scopes: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.scopes, Unset):
            scopes = []
            for scopes_item_data in self.scopes:
                scopes_item = scopes_item_data.to_dict()
                scopes.append(scopes_item)

        var_files: list[str] | Unset = UNSET
        if not isinstance(self.var_files, Unset):
            var_files = self.var_files

        variables: dict[str, Any] | Unset = UNSET
        if not isinstance(self.variables, Unset):
            variables = self.variables.to_dict()

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "workspace_path": workspace_path,
                "address": address,
                "resource_id": resource_id,
            }
        )
        if scopes is not UNSET:
            field_dict["scopes"] = scopes
        if var_files is not UNSET:
            field_dict["var_files"] = var_files
        if variables is not UNSET:
            field_dict["variables"] = variables

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.provider_scope import ProviderScope
        from ..models.variables import Variables

        d = dict(src_dict)
        workspace_path = d.pop("workspace_path")

        address = d.pop("address")

        resource_id = d.pop("resource_id")

        _scopes = d.pop("scopes", UNSET)
        scopes: list[ProviderScope] | Unset = UNSET
        if _scopes is not UNSET:
            scopes = []
            for scopes_item_data in _scopes:
                scopes_item = ProviderScope.from_dict(scopes_item_data)

                scopes.append(scopes_item)

        var_files = cast(list[str], d.pop("var_files", UNSET))

        _variables = d.pop("variables", UNSET)
        variables: Variables | Unset
        if isinstance(_variables, Unset):
            variables = UNSET
        else:
            variables = Variables.from_dict(_variables)

        import_request = cls(
            workspace_path=workspace_path,
            address=address,
            resource_id=resource_id,
            scopes=scopes,
            var_files=var_files,
            variables=variables,
        )

        return import_request
