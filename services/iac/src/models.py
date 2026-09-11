# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Pydantic models matching contracts/openapi/iac.v1.yaml."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


TargetStr = Annotated[str, Field(min_length=1, max_length=1024)]
# Single path segment only: `plan_file` is passed to `-out`, `show`,
# and `apply`, so it must not be able to escape the workspace.
PlanFileStr = Annotated[str, Field(pattern=r"^[A-Za-z0-9._-]{1,128}$")]


class InitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_path: str = Field(min_length=1, max_length=4096)
    scope_id: str | None = Field(default=None, max_length=1024)


class ValidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_path: str = Field(min_length=1, max_length=4096)
    scope_id: str | None = Field(default=None, max_length=1024)


class PlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_path: str = Field(min_length=1, max_length=4096)
    scope_id: str | None = Field(default=None, max_length=1024)
    targets: list[TargetStr] = Field(default_factory=list, max_length=256)
    plan_file: PlanFileStr


class ShowRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_path: str = Field(min_length=1, max_length=4096)
    scope_id: str | None = Field(default=None, max_length=1024)
    plan_file: PlanFileStr


class ApplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_path: str = Field(min_length=1, max_length=4096)
    scope_id: str | None = Field(default=None, max_length=1024)
    plan_file: PlanFileStr


class OperationResult(BaseModel):
    """Raw outcome of the single engine command a job ran."""

    model_config = ConfigDict(extra="forbid")

    exit_code: int
    stdout: str
    stderr: str


class Health(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"]


class Problem(BaseModel):
    model_config = ConfigDict(extra="allow")

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
]
JobStatus = Literal["queued", "running", "succeeded", "failed"]


class JobAccepted(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: UUID
    status: Literal["queued"] = "queued"


class Job(BaseModel):
    """All keys are always present; the nullable ones stay null until
    they become meaningful (``result`` iff succeeded, ``error`` iff
    failed)."""

    model_config = ConfigDict(extra="forbid")

    job_id: UUID
    kind: JobKind
    status: JobStatus
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    result: OperationResult | None
    error: Problem | None
