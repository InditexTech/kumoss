"""Pydantic models matching contracts/openapi/mapping.v1.yaml."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ResolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    identifier: str = Field(min_length=1, max_length=1024)
    cloud: str | None = Field(default=None, min_length=1, max_length=32)
    environment: str | None = Field(default=None, min_length=1, max_length=32)


class ResolveResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repo_url: str = Field(min_length=1, max_length=2048)
    project: str = Field(min_length=1, max_length=128)
    branch: str | None = Field(default=None, max_length=256)
    path: str | None = Field(default=None, max_length=1024)


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
