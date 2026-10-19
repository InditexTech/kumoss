# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""HTTP request/response envelopes owned by the API layer."""

from datetime import datetime
from typing import Any, ClassVar, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

from src.domains.services.operation_schedule_service import OperationScheduleService
from src.shared.constants import (
    OperationRole,
    OperationStatus,
    OperationType,
    PanelRole,
    TerraformProvider,
)


class AuthConfigResponse(BaseModel):
    """Public OIDC settings the SPA needs to run its login flow.

    Blank ``issuer_url`` means auth is disabled (dev mode).
    """

    issuer_url: str
    client_id: str
    audience: str
    scope: str
    artifact_metadata_header_prefix: str


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


class MappingResolveRequest(BaseModel):
    """Body of ``POST /v1/mapping/resolve``.

    Mirrors the mapping contract's ``ResolveRequest``.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    identifier: str = Field(
        min_length=1,
        max_length=1024,
        description="Business identifier to resolve.",
    )
    terraform_provider: TerraformProvider | None = Field(
        default=None,
        description=(
            "Provider the caller already knows the deployment targets, "
            "if any. Echoed back in the response."
        ),
    )


class MappingResolveResponse(BaseModel):
    """What the mapper knows about an identifier.

    Only ``repo_url`` is guaranteed. ``terraform_provider`` and
    ``scope_id`` are best effort, and ``null`` means "unknown, ask the
    user" rather than "there is none" — the wizard skips the step for
    whichever of them comes back non-null.
    """

    repo_url: str = Field(
        min_length=1,
        max_length=2048,
        description="URL to clone.",
    )
    identifier: str = Field(
        min_length=1,
        max_length=1024,
        description="The request's identifier, echoed verbatim.",
    )
    terraform_provider: TerraformProvider | None = Field(
        default=None,
        description="Provider the deployment targets, or null if unknown.",
    )
    scope_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=1024,
        description=(
            "Cloud scope the deployment targets — Azure subscription id, "
            "GCP project id, AWS account id, OCI compartment OCID — or "
            "null if unknown."
        ),
    )


class OperationAcceptedResponse(BaseModel):
    """A terraform operation was queued on ``session_id``."""

    session_id: UUID
    operation_id: UUID


class OperationResponse(BaseModel):
    uuid: UUID
    session_uuid: UUID
    schedule_uuid: UUID | None = None
    kind: OperationType
    status: OperationStatus
    params: dict[str, Any]
    scheduled_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None
    created_at: datetime


class PaginatedOperations(BaseModel):
    items: list[OperationResponse]
    total: int
    page: int
    page_size: int


class CreateScheduleRequest(BaseModel):
    """The owner is the authenticated caller; ``params`` is the first-call
    body of the matching ``/iac`` endpoint (repo_uri, terraform_providers,
    scope_id, q, ...)."""

    name: str = Field(min_length=1, max_length=254)
    kind: OperationType
    cron: str = Field(min_length=1, max_length=128)
    params: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True

    @field_validator("cron")
    @classmethod
    def _valid_cron(cls, cron: str | None) -> str | None:
        if cron is not None and not OperationScheduleService.is_valid_cron(cron):
            raise ValueError("Invalid cron expression.")
        return cron


class UpdateScheduleRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=254)
    cron: str | None = Field(default=None, min_length=1, max_length=128)
    params: dict[str, Any] | None = None
    enabled: bool | None = None

    @field_validator("cron")
    @classmethod
    def _valid_cron(cls, cron: str | None) -> str | None:
        if cron is not None and not OperationScheduleService.is_valid_cron(cron):
            raise ValueError("Invalid cron expression.")
        return cron


class ScheduleResponse(BaseModel):
    uuid: UUID
    owner_email: str | None = None
    name: str
    kind: OperationType
    cron: str
    enabled: bool
    params: dict[str, Any]
    next_run_at: datetime | None = None
    last_run_at: datetime | None = None
    created_at: datetime


class PaginatedSchedules(BaseModel):
    items: list[ScheduleResponse]
    total: int
    page: int
    page_size: int
