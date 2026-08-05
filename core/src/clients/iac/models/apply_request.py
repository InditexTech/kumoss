# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Self, TypeVar, cast

from attrs import define as _attrs_define

from ..types import UNSET, Unset

T = TypeVar("T", bound="ApplyRequest")


@_attrs_define
class ApplyRequest:
    """
    Attributes:
        workspace_path (str): Absolute filesystem path to the Terraform workspace as visible
            to the implementation. For the OSS docker-compose deployment,
            this is a path on the shared volume mounted into both the
            core and the IaC service.
        scope_id (None | str | Unset): Cloud provider scope the operation targets — Azure:
            subscription id, GCP: project id, AWS: account id. Used as a
            fallback when the credentials resolved for the workspace do
            not already carry a scope. Implementations MAY ignore it when
            the resolved credentials are fully specified.
        targets (list[str] | Unset): Optional `terraform plan -target=` filters. When omitted or
            empty, the entire configuration is planned and applied.
    """

    workspace_path: str
    scope_id: None | str | Unset = UNSET
    targets: list[str] | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        workspace_path = self.workspace_path

        scope_id: None | str | Unset
        if isinstance(self.scope_id, Unset):
            scope_id = UNSET
        else:
            scope_id = self.scope_id

        targets: list[str] | Unset = UNSET
        if not isinstance(self.targets, Unset):
            targets = self.targets

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "workspace_path": workspace_path,
            }
        )
        if scope_id is not UNSET:
            field_dict["scope_id"] = scope_id
        if targets is not UNSET:
            field_dict["targets"] = targets

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        workspace_path = d.pop("workspace_path")

        def _parse_scope_id(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        scope_id = _parse_scope_id(d.pop("scope_id", UNSET))

        targets = cast(list[str], d.pop("targets", UNSET))

        apply_request = cls(
            workspace_path=workspace_path,
            scope_id=scope_id,
            targets=targets,
        )

        return apply_request
