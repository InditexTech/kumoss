# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""HTTP request/response envelopes owned by the API layer."""

from datetime import datetime
from typing import Any, ClassVar, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from src.shared.constants import OperationRole, PanelRole


class AuthConfigResponse(BaseModel):
    """Public OIDC settings the SPA needs to run its login flow.

    Blank ``issuer_url`` means auth is disabled (dev mode).
    """

    issuer_url: str
    client_id: str
    audience: str
    scope: str


class UserMeResponse(BaseModel):
    """The caller's identity and roles, as the SPA consumes them."""

    id: int
    email: str | None
    display_name: str | None
    operation_role: OperationRole
    panel_role: PanelRole | None


class AdminUserEntry(UserMeResponse):
    issuer: str
    subject: str
    created_at: datetime


class PaginatedUsers(BaseModel):
    items: list[AdminUserEntry]
    total: int
    page: int
    page_size: int
    total_pages: int


class UpdateUserRolesRequest(BaseModel):
    """Full-state role assignment; panel_role None clears panel access."""

    operation_role: OperationRole
    panel_role: PanelRole | None = None


class SessionLockResponse(BaseModel):
    uuid: UUID
    is_blocked: bool


class NotificationLink(BaseModel):
    """A link the notifications service may render as a button."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=128)
    url: HttpUrl = Field(max_length=2048)


class SubmitNotificationRequest(BaseModel):
    """Body of ``POST /v1/notifications``.

    Mirrors the contract's ``NotificationRequest`` except for ``audience``,
    which the core derives from the authenticated caller and the users
    store instead of trusting the client.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    kind: str = Field(
        min_length=1,
        max_length=128,
        description="Event category, dotted lowercase (e.g. support.user_question).",
    )
    severity: Literal["info", "warning", "error", "critical"]
    subject: str = Field(min_length=1, max_length=256)
    body: str = Field(min_length=1, max_length=16384)
    links: list[NotificationLink] = Field(default_factory=list, max_length=32)
    context: dict[str, Any] = Field(default_factory=dict)


class NotificationAcceptedResponse(BaseModel):
    """The notifications service's delivery id for an accepted request."""

    delivery_id: UUID
