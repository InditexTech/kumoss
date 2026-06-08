"""Pydantic models matching contracts/openapi/notifications.v1.yaml.

Hand-written here rather than imported from a generated client because the
service implements the contract — it doesn't consume it. The shapes must
match the spec; the conformance suite under contracts/conformance/ is the
authoritative check.
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


Severity = Literal["info", "warning", "error", "critical"]


class Link(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=128)
    url: HttpUrl = Field(max_length=2048)


class NotificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str = Field(min_length=1, max_length=128)
    severity: Severity
    subject: str = Field(min_length=1, max_length=256)
    body: str = Field(min_length=1, max_length=16384)
    audience: list[str] = Field(default_factory=list, max_length=256)
    links: list[Link] = Field(default_factory=list, max_length=32)
    context: dict[str, Any] = Field(default_factory=dict)


class NotificationAccepted(BaseModel):
    model_config = ConfigDict(extra="forbid")

    delivery_id: UUID


class Health(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"]


class Problem(BaseModel):
    """RFC 7807 problem details."""

    model_config = ConfigDict(extra="allow")

    type: str = "about:blank"
    title: str
    status: int = Field(ge=100, le=599)
    detail: str | None = None
    instance: str | None = None
