# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Self, TypeVar

from attrs import define as _attrs_define

from ..models.terraform_provider import TerraformProvider

T = TypeVar("T", bound="ScopeResourceIdsRequest")


@_attrs_define
class ScopeResourceIdsRequest:
    """
    Attributes:
        workspace_path (str): Absolute filesystem path to the Terraform workspace as visible
            to the implementation. For the OSS docker-compose deployment,
            this is a path on the shared volume mounted into both the
            core and the IaC service. Used to resolve the provider
            credentials the scope query runs with.
        scope_id (str): Cloud provider scope to list — Azure: subscription id (or
            any value matched as a substring of resource IDs), GCP:
            project id, AWS: account id. Names the scope being listed
            rather than the scope a command runs against.
        terraform_provider (TerraformProvider): Cloud provider a scope query targets. Values follow the core's
            provider vocabulary (`azure`, `gcp`, `aws`), not Terraform
            registry provider names (`azurerm`, `google`).
    """

    workspace_path: str
    scope_id: str
    terraform_provider: TerraformProvider

    def to_dict(self) -> dict[str, Any]:
        workspace_path = self.workspace_path

        scope_id = self.scope_id

        terraform_provider = self.terraform_provider.value

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "workspace_path": workspace_path,
                "scope_id": scope_id,
                "terraform_provider": terraform_provider,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        workspace_path = d.pop("workspace_path")

        scope_id = d.pop("scope_id")

        terraform_provider = TerraformProvider(d.pop("terraform_provider"))

        scope_resource_ids_request = cls(
            workspace_path=workspace_path,
            scope_id=scope_id,
            terraform_provider=terraform_provider,
        )

        return scope_resource_ids_request
