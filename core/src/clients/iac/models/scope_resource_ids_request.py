# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Self, TypeVar

from attrs import define as _attrs_define

from ..models.scope_resource_ids_request_provider import ScopeResourceIdsRequestProvider

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
        scope_id (str): Cloud provider scope to list — `azurerm`: subscription id,
            `google`: project id, `aws`: account id. Each is validated for its
            cloud's shape, and a scope the credentials do not own ends
            the job with exit code 1. Names the scope being listed
            rather than the scope a command runs against.
        provider (ScopeResourceIdsRequestProvider): Terraform provider type name of the cloud the scope query
            targets. Only the providers with an inventory query are
            accepted.
    """

    workspace_path: str
    scope_id: str
    provider: ScopeResourceIdsRequestProvider

    def to_dict(self) -> dict[str, Any]:
        workspace_path = self.workspace_path

        scope_id = self.scope_id

        provider = self.provider.value

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "workspace_path": workspace_path,
                "scope_id": scope_id,
                "provider": provider,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        workspace_path = d.pop("workspace_path")

        scope_id = d.pop("scope_id")

        provider = ScopeResourceIdsRequestProvider(d.pop("provider"))

        scope_resource_ids_request = cls(
            workspace_path=workspace_path,
            scope_id=scope_id,
            provider=provider,
        )

        return scope_resource_ids_request
