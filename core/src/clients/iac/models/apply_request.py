# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Self, TypeVar

from attrs import define as _attrs_define

from ..models.terraform_provider import TerraformProvider

T = TypeVar("T", bound="ApplyRequest")


@_attrs_define
class ApplyRequest:
    """
    Attributes:
        workspace_path (str): Absolute filesystem path to the Terraform workspace as visible
            to the implementation. For the OSS docker-compose deployment,
            this is a path on the shared volume mounted into both the
            core and the IaC service.
        scope_id (str): Cloud provider scope the operation targets — Azure:
            subscription id, GCP: project id, AWS: account id, OCI:
            tenancy OCID. Required: generated provider blocks do not
            carry a scope, so the implementation injects it into the
            engine's environment for this command only, choosing the
            variable from `terraform_provider` (see "Scope injection").
        terraform_provider (TerraformProvider): Cloud provider a request targets. Values follow the core's
            provider vocabulary (`azure`, `gcp`, `aws`, `oci`,
            `kubernetes`), not Terraform registry provider names
            (`azurerm`, `google`).
        plan_file (str): Filename (not a path) of a plan file previously written by a
            `plan` job on this workspace; `apply` executes exactly the
            changes recorded in it. Restricted to a single path segment
            so it cannot escape the workspace.
    """

    workspace_path: str
    scope_id: str
    terraform_provider: TerraformProvider
    plan_file: str

    def to_dict(self) -> dict[str, Any]:
        workspace_path = self.workspace_path

        scope_id = self.scope_id

        terraform_provider = self.terraform_provider.value

        plan_file = self.plan_file

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "workspace_path": workspace_path,
                "scope_id": scope_id,
                "terraform_provider": terraform_provider,
                "plan_file": plan_file,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        workspace_path = d.pop("workspace_path")

        scope_id = d.pop("scope_id")

        terraform_provider = TerraformProvider(d.pop("terraform_provider"))

        plan_file = d.pop("plan_file")

        apply_request = cls(
            workspace_path=workspace_path,
            scope_id=scope_id,
            terraform_provider=terraform_provider,
            plan_file=plan_file,
        )

        return apply_request
