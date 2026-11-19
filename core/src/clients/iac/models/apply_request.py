# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Self, TypeVar

from attrs import define as _attrs_define

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.env import Env


T = TypeVar("T", bound="ApplyRequest")


@_attrs_define
class ApplyRequest:
    """
    Attributes:
        workspace_path (str): Absolute filesystem path to the Terraform workspace as visible
            to the implementation. For the OSS docker-compose deployment,
            this is a path on the shared volume mounted into both the
            core and the IaC service.
        plan_file (str): Filename (not a path) of a plan file previously written by a
            `plan` job on this workspace; `apply` executes exactly the
            changes recorded in it. Restricted to a single path segment
            so it cannot escape the workspace.
        env (Env | Unset): Environment variables added to the command's environment. Names
            the implementation's own environment already sets, and the
            reserved names listed in "Environment and input variables"
            (`TF_*` but `TF_VAR_*`, `TOFU_*`, `LD_*`, proxies, ...), are
            rejected with `422`. May contain secrets.
    """

    workspace_path: str
    plan_file: str
    env: Env | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        workspace_path = self.workspace_path

        plan_file = self.plan_file

        env: dict[str, Any] | Unset = UNSET
        if not isinstance(self.env, Unset):
            env = self.env.to_dict()

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "workspace_path": workspace_path,
                "plan_file": plan_file,
            }
        )
        if env is not UNSET:
            field_dict["env"] = env

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.env import Env

        d = dict(src_dict)
        workspace_path = d.pop("workspace_path")

        plan_file = d.pop("plan_file")

        _env = d.pop("env", UNSET)
        env: Env | Unset
        if isinstance(_env, Unset):
            env = UNSET
        else:
            env = Env.from_dict(_env)

        apply_request = cls(
            workspace_path=workspace_path,
            plan_file=plan_file,
            env=env,
        )

        return apply_request
