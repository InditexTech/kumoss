# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Pydantic models matching contracts/openapi/authz.v1.yaml."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str | None = Field(default=None, min_length=1, max_length=1024)
    cloud: str = Field(min_length=1, max_length=32)
    project: str = Field(min_length=1, max_length=256)
    environment: str | None = Field(default=None, min_length=1, max_length=32)


class CheckResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    authorized: bool
    portal_url: str | None = Field(default=None, max_length=2048)
    reason: str | None = Field(default=None, max_length=1024)


class User(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=1024)
    email: str | None = Field(default=None, max_length=256)
    name: str | None = Field(default=None, max_length=256)
    roles: list[str] = Field(default_factory=list)


class UserList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    users: list[User]


class Role(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=512)


class RoleList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    roles: list[Role]


class AssignRoleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str = Field(min_length=1, max_length=64)


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
