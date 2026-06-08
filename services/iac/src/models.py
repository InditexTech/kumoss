# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Pydantic models matching contracts/openapi/validation.v1.yaml."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ValidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_path: str = Field(min_length=1, max_length=4096)
    branch: str | None = Field(default=None, max_length=256)
    targets: list[str] = Field(default_factory=list, max_length=256)
    get_drift: bool = False


class ValidateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    validation: bool
    feedback: str
    terraform_plan: str
    terraform_targets: list[str]


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
