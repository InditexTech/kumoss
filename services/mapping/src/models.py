# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Pydantic models matching contracts/openapi/mapping.v1.yaml."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class TerraformProvider(str, Enum):
    AZURE = "azure"
    GCP = "gcp"
    AWS = "aws"
    OCI = "oci"
    KUBERNETES = "kubernetes"


class ResolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    identifier: str = Field(min_length=1, max_length=1024)
    terraform_provider: TerraformProvider | None = None


class ResolveResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repo_url: str = Field(
        min_length=1, max_length=2048, pattern=r"^[Hh][Tt][Tt][Pp][Ss]://"
    )
    identifier: str = Field(min_length=1, max_length=1024)
    terraform_provider: TerraformProvider | None = None
    scope_id: str | None = Field(default=None, min_length=1, max_length=1024)


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
