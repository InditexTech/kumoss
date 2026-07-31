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


class ValidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_path: str = Field(min_length=1, max_length=4096)
    scope_id: str | None = Field(default=None, max_length=1024)
    branch: str | None = Field(default=None, max_length=256)
    targets: list[TargetStr] = Field(default_factory=list, max_length=256)
    get_drift: bool = False


class ValidateResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    validation: bool
    feedback: str
    terraform_plan: str
    terraform_targets: list[str]


class ApplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_path: str = Field(min_length=1, max_length=4096)
    scope_id: str | None = Field(default=None, max_length=1024)
    targets: list[TargetStr] = Field(default_factory=list, max_length=256)


class ApplyResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    success: bool
    feedback: str
    terraform_output: str


class ImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_path: str = Field(min_length=1, max_length=4096)
    scope_id: str | None = Field(default=None, max_length=1024)
    address: str = Field(min_length=1, max_length=4096)
    resource_id: str = Field(min_length=1, max_length=4096)


class ImportResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    success: bool
    feedback: str


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


JobKind = Literal["validate", "apply", "import"]
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
    result: ValidateResult | ApplyResult | ImportResult | None
    error: Problem | None
