# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Self, TypeVar, cast

from attrs import define as _attrs_define

from ..types import UNSET, Unset

T = TypeVar("T", bound="ShowRequest")


@_attrs_define
class ShowRequest:
    """
    Attributes:
        workspace_path (str): Absolute filesystem path to the Terraform workspace as visible
            to the implementation. For the OSS docker-compose deployment,
            this is a path on the shared volume mounted into both the
            core and the IaC service.
        plan_file (str): Filename (not a path) of a plan file previously written by a
            `plan` job on this workspace. Restricted to a single path
            segment so it cannot escape the workspace.
        scope_id (None | str | Unset): Cloud provider scope the operation targets — Azure:
            subscription id, GCP: project id, AWS: account id. Used as a
            fallback when the credentials resolved for the workspace do
            not already carry a scope. Implementations MAY ignore it when
            the resolved credentials are fully specified.
    """

    workspace_path: str
    plan_file: str
    scope_id: None | str | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        workspace_path = self.workspace_path

        plan_file = self.plan_file

        scope_id: None | str | Unset
        if isinstance(self.scope_id, Unset):
            scope_id = UNSET
        else:
            scope_id = self.scope_id

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "workspace_path": workspace_path,
                "plan_file": plan_file,
            }
        )
        if scope_id is not UNSET:
            field_dict["scope_id"] = scope_id

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        workspace_path = d.pop("workspace_path")

        plan_file = d.pop("plan_file")

        def _parse_scope_id(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        scope_id = _parse_scope_id(d.pop("scope_id", UNSET))

        show_request = cls(
            workspace_path=workspace_path,
            plan_file=plan_file,
            scope_id=scope_id,
        )

        return show_request
