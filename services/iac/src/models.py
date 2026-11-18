# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Pydantic models matching contracts/openapi/iac.v1.yaml."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, ClassVar, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator


TargetStr = Annotated[str, Field(min_length=1, max_length=1024)]
# Single path segment only: `plan_file` is passed to `-out`, `show`,
# and `apply`, so it must not be able to escape the workspace.
PlanFileStr = Annotated[str, Field(pattern=r"^[A-Za-z0-9._-]{1,128}$")]
ScopeIdStr = Annotated[str, Field(min_length=1, max_length=1024)]
AddressStr = Annotated[str, Field(min_length=1, max_length=4096)]
ResourceIdStr = Annotated[str, Field(min_length=1, max_length=4096)]

# Relative to the workspace, plain segments only (no `.`, `..`, hidden
# or leading `/`), so a var file can neither escape the workspace nor be
# confused with anything Terraform itself manages. Mirrors the contract.
VarFileStr = Annotated[
    str,
    Field(
        max_length=1024,
        pattern=r"^[A-Za-z0-9_-][A-Za-z0-9._-]*(/[A-Za-z0-9_-][A-Za-z0-9._-]*)*\.tfvars(\.json)?$",
    ),
]
VariableNameStr = Annotated[str, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_-]{0,127}$")]

# Terraform provider type name: the last segment of its source address
# (`azurerm` for `hashicorp/azurerm`). Any provider is accepted.
ProviderStr = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")]
# The providers scope discovery can list.
DiscoveryProvider = Literal["azurerm", "google", "aws"]


class WorkspaceRequest(BaseModel):
    """The one field every submit request carries.

    Also the body model the ``resolve_workspace`` dependency binds to:
    it sees only ``workspace_path`` and ignores the operation-specific
    rest, which the endpoint's own model validates.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    workspace_path: str = Field(min_length=1, max_length=4096)


class ProviderScope(BaseModel):
    """The scope one provider of the root module runs against."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    provider: ProviderStr
    scope_id: ScopeIdStr


class ScopedRequest(WorkspaceRequest):
    """Base for the commands whose scopes decide what they run against.

    The commands that take no scope extend ``WorkspaceRequest``
    directly: they declare no ``scopes``, and ``extra="forbid"`` makes
    sending one a 422.
    """

    scopes: list[ProviderScope] = Field(default_factory=list, max_length=64)

    @field_validator("scopes")
    @classmethod
    def _one_scope_per_provider(
        cls, scopes: list[ProviderScope]
    ) -> list[ProviderScope]:
        seen: set[str] = set()
        for scope in scopes:
            if scope.provider in seen:
                raise ValueError(f"provider '{scope.provider}' appears more than once")
            seen.add(scope.provider)
        return scopes


class InputsRequest(ScopedRequest):
    """Base for the commands that evaluate the configuration's input variables.

    ``variables`` may hold secrets: it is excluded from ``repr`` and
    must never be logged (see the contract's "Input variables").
    """

    var_files: list[VarFileStr] = Field(default_factory=list, max_length=64)
    variables: dict[VariableNameStr, JsonValue] = Field(
        default_factory=dict, max_length=1024, repr=False
    )


class InitRequest(ScopedRequest):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")


class ValidateRequest(WorkspaceRequest):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")


class PlanRequest(InputsRequest):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    targets: list[TargetStr] = Field(default_factory=list, max_length=4096)
    plan_file: PlanFileStr


class ShowRequest(WorkspaceRequest):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    plan_file: PlanFileStr


class ApplyRequest(ScopedRequest):
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
