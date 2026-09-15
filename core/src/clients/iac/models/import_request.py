# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Self, TypeVar

from attrs import define as _attrs_define

from ..models.terraform_provider import TerraformProvider

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
            GCP: project id, AWS: account id, OCI: compartment OCID.
            Required: generated provider blocks do not carry a scope,
            so where the cloud has a provider-level variable for one
            the implementation injects it into the engine's
            environment for this command only (see "Scope injection").
        terraform_provider (TerraformProvider): Cloud provider a request targets. Values follow the core's
            provider vocabulary (`azure`, `gcp`, `aws`, `oci`,
            `kubernetes`), not Terraform registry provider names
            (`azurerm`, `google`).
        address (str): Terraform resource address to import into, e.g.
            `azurerm_resource_group.main`.
        resource_id (str): Provider-specific identifier of the existing cloud resource,
            e.g. an Azure resource ID or an AWS ARN.
    """

    workspace_path: str
    scope_id: str
    terraform_provider: TerraformProvider
    address: str
    resource_id: str

    def to_dict(self) -> dict[str, Any]:
        workspace_path = self.workspace_path

        scope_id = self.scope_id

        terraform_provider = self.terraform_provider.value

        address = self.address

        resource_id = self.resource_id

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

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        workspace_path = d.pop("workspace_path")

        scope_id = d.pop("scope_id")

        terraform_provider = TerraformProvider(d.pop("terraform_provider"))

        address = d.pop("address")

        resource_id = d.pop("resource_id")

        import_request = cls(
            workspace_path=workspace_path,
            scope_id=scope_id,
            terraform_provider=terraform_provider,
            address=address,
            resource_id=resource_id,
        )

        return import_request
