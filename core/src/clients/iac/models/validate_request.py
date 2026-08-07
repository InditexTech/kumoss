# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Self, TypeVar, cast

from attrs import define as _attrs_define

from ..types import UNSET, Unset

T = TypeVar("T", bound="ValidateRequest")


@_attrs_define
class ValidateRequest:
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
        branch (None | str | Unset): Informational: the branch name the workspace was checked out
            from. Implementations MAY include it in logs / traces but the
            actual validation operates on whatever is currently on disk
            at `workspace_path`.
        targets (list[str] | Unset): Optional `terraform plan -target=` filters. When omitted or
            empty, the entire configuration is planned.
        get_drift (bool | Unset): When true and the plan succeeds, the implementation parses
            the plan JSON and summarises any resource changes (drift) in
            the `feedback` field of the job result, with `validation`
            set to `false` if drift is non-empty. Useful for "is
            anything different from what's deployed?" queries.
             Default: False.
    """

    workspace_path: str
    scope_id: None | str | Unset = UNSET
    branch: None | str | Unset = UNSET
    targets: list[str] | Unset = UNSET
    get_drift: bool | Unset = False

    def to_dict(self) -> dict[str, Any]:
        workspace_path = self.workspace_path

        scope_id: None | str | Unset
        if isinstance(self.scope_id, Unset):
            scope_id = UNSET
        else:
            scope_id = self.scope_id

        branch: None | str | Unset
        if isinstance(self.branch, Unset):
            branch = UNSET
        else:
            branch = self.branch

        targets: list[str] | Unset = UNSET
        if not isinstance(self.targets, Unset):
            targets = self.targets

        get_drift = self.get_drift

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "workspace_path": workspace_path,
            }
        )
        if scope_id is not UNSET:
            field_dict["scope_id"] = scope_id
        if branch is not UNSET:
            field_dict["branch"] = branch
        if targets is not UNSET:
            field_dict["targets"] = targets
        if get_drift is not UNSET:
            field_dict["get_drift"] = get_drift

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

        def _parse_branch(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        branch = _parse_branch(d.pop("branch", UNSET))

        targets = cast(list[str], d.pop("targets", UNSET))

        get_drift = d.pop("get_drift", UNSET)

        validate_request = cls(
            workspace_path=workspace_path,
            scope_id=scope_id,
            branch=branch,
            targets=targets,
            get_drift=get_drift,
        )

        return validate_request
