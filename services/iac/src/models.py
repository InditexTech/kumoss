# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Pydantic models matching contracts/openapi/iac.v1.yaml."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, ClassVar, Literal
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, JsonValue


TargetStr = Annotated[str, Field(min_length=1, max_length=1024)]
# Single path segment only: `plan_file` is passed to `-out`, `show`,
# and `apply`, so it must not be able to escape the workspace.
PlanFileStr = Annotated[str, Field(pattern=r"^[A-Za-z0-9._-]{1,128}$")]
ScopeIdStr = Annotated[str, Field(min_length=1, max_length=1024)]
AddressStr = Annotated[str, Field(min_length=1, max_length=4096)]
ResourceIdStr = Annotated[str, Field(min_length=1, max_length=4096)]

VariableNameStr = Annotated[str, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_-]{0,127}$")]
EnvNameStr = Annotated[str, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")]
# No NUL: the OS cannot pass one to a process, so it would fail the job.
EnvValueStr = Annotated[str, Field(max_length=32768, pattern=r"^[^\x00]*$")]


def _relative_var_file(path: str) -> str:
    """Relative to the workspace, without `..` segments or NUL.

    Any other shape is fine: the path is one argv entry, never seen by a
    shell. The engine still checks it resolves inside the workspace
    (symlinks).
    """
    if path.startswith("/") or ".." in path.split("/") or "\x00" in path:
        raise ValueError("must be relative to the workspace, without '..' or NUL")
    return path


VarFileStr = Annotated[
    str, Field(min_length=1, max_length=1024), AfterValidator(_relative_var_file)
]

# The providers scope discovery can list, by Terraform provider type name.
DiscoveryProvider = Literal["azurerm", "google", "aws"]


class WorkspaceRequest(BaseModel):
    """The one field every submit request carries.

    Also the body model the ``resolve_workspace`` dependency binds to:
    it sees only ``workspace_path`` and ignores the operation-specific
    rest, which the endpoint's own model validates.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    workspace_path: str = Field(min_length=1, max_length=4096)


class CommandRequest(WorkspaceRequest):
    """Base for the endpoints that run one engine command.

    ``env`` is added to the command's environment; the endpoint rejects
    names that would replace one (see ``main.check_env``). Values may be
    secrets: excluded from ``repr`` and never logged.
    """

    env: dict[EnvNameStr, EnvValueStr] = Field(
        default_factory=dict, max_length=256, repr=False
    )


class InputsRequest(CommandRequest):
    """Base for the commands that evaluate the configuration's input variables.

    ``vars`` may hold secrets: it is excluded from ``repr`` and must
    never be logged (see the contract's "Environment and input
    variables").
    """

    var_files: list[VarFileStr] = Field(default_factory=list, max_length=64)
    vars: dict[VariableNameStr, JsonValue] = Field(
        default_factory=dict, max_length=1024, repr=False
    )


class InitRequest(CommandRequest):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")


class ValidateRequest(CommandRequest):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")


class PlanRequest(InputsRequest):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    targets: list[TargetStr] = Field(default_factory=list, max_length=4096)
    plan_file: PlanFileStr


class ShowRequest(CommandRequest):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    plan_file: PlanFileStr


class ApplyRequest(CommandRequest):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    plan_file: PlanFileStr


class ImportRequest(InputsRequest):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    address: AddressStr
    resource_id: ResourceIdStr


class StateResourceIdsRequest(WorkspaceRequest):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")


class ScopeResourceIdsRequest(WorkspaceRequest):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    scope_id: ScopeIdStr
    provider: DiscoveryProvider


class OperationResult(BaseModel):
    """Raw outcome of the single engine command a job ran."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    exit_code: int
    stdout: str
    stderr: str


class Health(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    status: Literal["ok"]


class Problem(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="allow")

    type: str = "about:blank"
    title: str
    status: int = Field(ge=100, le=599)
    detail: str | None = None
    instance: str | None = None


JobKind = Literal[
    "init",
    "validate",
    "plan",
    "show",
    "apply",
    "import",
    "state_resource_ids",
    "scope_resource_ids",
]
JobStatus = Literal["queued", "running", "succeeded", "failed"]


class JobAccepted(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    job_id: UUID
    status: Literal["queued"] = "queued"


class Job(BaseModel):
    """All keys are always present; the nullable ones stay null until
    they become meaningful (``result`` iff succeeded, ``error`` iff
    failed)."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    job_id: UUID
    kind: JobKind
    status: JobStatus
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    result: OperationResult | None
    error: Problem | None
