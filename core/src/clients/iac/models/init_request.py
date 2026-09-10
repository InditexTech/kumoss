# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Self, TypeVar

from attrs import define as _attrs_define

T = TypeVar("T", bound="InitRequest")


@_attrs_define
class InitRequest:
    """
    Attributes:
        workspace_path (str): Absolute filesystem path to the Terraform workspace as visible
            to the implementation. For the OSS docker-compose deployment,
            this is a path on the shared volume mounted into both the
            core and the IaC service.
        scope_id (str): Cloud provider scope the operation targets — Azure:
            subscription id, GCP: project id, AWS: account id. Required:
            generated provider blocks do not carry a scope, so the
            implementation injects it into the engine's environment
            (e.g. `ARM_SUBSCRIPTION_ID` / `GOOGLE_PROJECT`, or an AWS
            AssumeRole for the account) for this command only.
    """

    workspace_path: str
    scope_id: str

    def to_dict(self) -> dict[str, Any]:
        workspace_path = self.workspace_path

        scope_id = self.scope_id

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "workspace_path": workspace_path,
                "scope_id": scope_id,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        workspace_path = d.pop("workspace_path")

        scope_id = d.pop("scope_id")

        init_request = cls(
            workspace_path=workspace_path,
            scope_id=scope_id,
        )

        return init_request
