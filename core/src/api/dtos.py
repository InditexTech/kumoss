# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""HTTP request/response envelopes owned by the API layer."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

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
