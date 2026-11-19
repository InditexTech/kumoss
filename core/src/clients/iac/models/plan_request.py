# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Self, TypeVar, cast

from attrs import define as _attrs_define

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.env import Env
    from ..models.vars_ import Vars


T = TypeVar("T", bound="PlanRequest")


@_attrs_define
class PlanRequest:
    """
    Attributes:
        workspace_path (str): Absolute filesystem path to the Terraform workspace as visible
            to the implementation. For the OSS docker-compose deployment,
            this is a path on the shared volume mounted into both the
            core and the IaC service.
        plan_file (str): Filename (not a path) the plan is written to via
            `-out <plan_file>`, relative to the workspace root. The
            caller passes the same name to subsequent `show` / `apply`
            jobs. Restricted to a single path segment so it cannot
            escape the workspace.
        env (Env | Unset): Environment variables added to the command's environment. Names
            the implementation's own environment already sets, and
            `TF_CLI_ARGS`, `TF_CLI_ARGS_*` and `TF_DATA_DIR`, are rejected
            with `422`. May contain secrets. See "Environment and input
            variables".
        targets (list[str] | Unset): Optional `terraform plan -target=` filters. When omitted or
            empty, the entire configuration is planned.
        vars_ (Vars | Unset): Input variable values by name, of any JSON type, passed as the
            last `-var-file` so they win over every other source. May
            contain secrets: never logged, persisted, or written inside the
            workspace. See "Environment and input variables".
    """

    workspace_path: str
    plan_file: str
    env: Env | Unset = UNSET
    targets: list[str] | Unset = UNSET
    vars_: Vars | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        workspace_path = self.workspace_path

        plan_file = self.plan_file

        env: dict[str, Any] | Unset = UNSET
        if not isinstance(self.env, Unset):
            env = self.env.to_dict()

        targets: list[str] | Unset = UNSET
        if not isinstance(self.targets, Unset):
            targets = self.targets

        vars_: dict[str, Any] | Unset = UNSET
        if not isinstance(self.vars_, Unset):
            vars_ = self.vars_.to_dict()

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "workspace_path": workspace_path,
                "plan_file": plan_file,
            }
        )
        if env is not UNSET:
            field_dict["env"] = env
        if targets is not UNSET:
            field_dict["targets"] = targets
        if vars_ is not UNSET:
            field_dict["vars"] = vars_

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.env import Env
        from ..models.vars_ import Vars

        d = dict(src_dict)
        workspace_path = d.pop("workspace_path")

        plan_file = d.pop("plan_file")

        _env = d.pop("env", UNSET)
        env: Env | Unset
        if isinstance(_env, Unset):
            env = UNSET
        else:
            env = Env.from_dict(_env)

        targets = cast(list[str], d.pop("targets", UNSET))

        _vars_ = d.pop("vars", UNSET)
        vars_: Vars | Unset
        if isinstance(_vars_, Unset):
            vars_ = UNSET
        else:
            vars_ = Vars.from_dict(_vars_)

        plan_request = cls(
            workspace_path=workspace_path,
            plan_file=plan_file,
            env=env,
            targets=targets,
            vars_=vars_,
        )

        return plan_request
