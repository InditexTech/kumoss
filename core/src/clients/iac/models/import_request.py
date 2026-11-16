# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Self, TypeVar, cast

from attrs import define as _attrs_define

from ..models.terraform_provider import TerraformProvider
from ..types import UNSET, Unset

if TYPE_CHECKING:
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
        scope_id (str): Cloud scope the operation targets — Azure: subscription id,
            GCP: project id, AWS: account id, OCI: compartment OCID,
            VMware: vSphere datacenter name.
            Required: generated provider blocks do not carry a scope,
            so where the cloud has an environment variable for one
            the implementation injects it into the engine's
            environment for this command only (see "Scope injection").
        terraform_provider (TerraformProvider): Cloud provider a request targets. Values follow the core's
            provider vocabulary (`azure`, `gcp`, `aws`, `oci`,
            `kubernetes`, `vmware`), not Terraform registry provider names
            (`azurerm`, `google`).
        address (str): Terraform resource address to import into, e.g.
            `azurerm_resource_group.main`.
        resource_id (str): Provider-specific identifier of the existing cloud resource,
            e.g. an Azure resource ID or an AWS ARN.
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
    scope_id: str
    terraform_provider: TerraformProvider
    address: str
    resource_id: str
    var_files: list[str] | Unset = UNSET
    variables: Variables | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        workspace_path = self.workspace_path

        scope_id = self.scope_id

        terraform_provider = self.terraform_provider.value

        address = self.address

        resource_id = self.resource_id

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
                "scope_id": scope_id,
                "terraform_provider": terraform_provider,
                "address": address,
                "resource_id": resource_id,
            }
        )
        if var_files is not UNSET:
            field_dict["var_files"] = var_files
        if variables is not UNSET:
            field_dict["variables"] = variables

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.variables import Variables

        d = dict(src_dict)
        workspace_path = d.pop("workspace_path")

        scope_id = d.pop("scope_id")

        terraform_provider = TerraformProvider(d.pop("terraform_provider"))

        address = d.pop("address")

        resource_id = d.pop("resource_id")

        var_files = cast(list[str], d.pop("var_files", UNSET))

        _variables = d.pop("variables", UNSET)
        variables: Variables | Unset
        if isinstance(_variables, Unset):
            variables = UNSET
        else:
            variables = Variables.from_dict(_variables)

        import_request = cls(
            workspace_path=workspace_path,
            scope_id=scope_id,
            terraform_provider=terraform_provider,
            address=address,
            resource_id=resource_id,
            var_files=var_files,
            variables=variables,
        )

        return import_request
