# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import math
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query
from pydantic import BaseModel

from src.domains.services.database_service import DatabaseService
from src.infrastructure.database.models import UserSession
from src.infrastructure.external.authz_service import AuthzServiceClient

_TERMINAL_STATUSES = ("completed", "abandoned")


class SessionSummaryResponse(BaseModel):
    # Persisted columns
    session_id: str
    user_id: str
    repo_uri: str
    cloud_provider: str
    environment: str
    branch_name: str
    status: str
    in_flight: bool
    created_at: datetime
    updated_at: datetime
    # Restored persisted observability columns
    operation_type: str
    failure_reason: str | None = None
    pull_request_url: str | None = None
    apply_allowed: bool
    iac_path: str | None = None
    # Computed / inferable fields (no schema change needed)
    is_active: bool
    current_status: str
    final_status: str | None = None
    initial_query: str | None = None
    repository_id: str
    completed_at: datetime | None = None
    duration_seconds: float | None = None

    @classmethod
    def from_row(cls, row: UserSession) -> "SessionSummaryResponse":
        is_terminal = row.status in _TERMINAL_STATUSES
        return cls(
            session_id=row.session_id,
            user_id=row.user_id,
            repo_uri=row.repo_uri,
            cloud_provider=row.cloud_provider,
            environment=row.environment,
            branch_name=row.branch_name,
            status=row.status,
            in_flight=row.in_flight,
            created_at=row.created_at,
            updated_at=row.updated_at,
            operation_type=row.operation_type,
            failure_reason=row.failure_reason,
            pull_request_url=row.pull_request_url,
            apply_allowed=row.apply_allowed,
            iac_path=row.iac_path,
            # Computed fields
            is_active=(row.status == "active"),
            current_status=row.status,
            final_status=row.status if is_terminal else None,
            initial_query=row.history[0]["user"] if row.history else None,
            repository_id=row.repo_uri,
            completed_at=row.updated_at if is_terminal else None,
            duration_seconds=(
                (row.updated_at - row.created_at).total_seconds()
                if is_terminal
                else None
            ),
        )


class PaginatedSessionsResponse(BaseModel):
    items: list[SessionSummaryResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class OperationResponse(BaseModel):
    id: int
    operation_number: int
    operation_type: str
    operation_phase: str | None = None
    operation_subtype: str | None = None
    success: bool | None = None
    duration_seconds: float | None = None
    error_message: str | None = None
    artifact_type: str | None = None
    blob_url: str | None = None
    file_size_bytes: int | None = None
    content_type: str | None = None
    terraform_targets: list | None = None
    pipeline_run_id: str | None = None
    created_at: datetime


class SessionDetailResponse(BaseModel):
    session: SessionSummaryResponse
    operations: list[OperationResponse]


async def require_admin(x_user_id: str = Header(...)) -> None:
    """Admin gate: caller's X-User-Id must hold the `admin` role on the
    authz service. Identity is asserted by the core's OIDC layer upstream
    of this header; the authz service is the role authority."""
    if not await AuthzServiceClient().is_admin(x_user_id):
        raise HTTPException(status_code=403, detail="Admin access denied")


router = APIRouter(
    prefix="/admin", tags=["Admin"], dependencies=[Depends(require_admin)]
)


@router.get("/sessions", summary="List sessions with pagination and filters")
async def list_sessions(
    page: Annotated[int, Query(1, ge=1)],
    page_size: Annotated[int, Query(20, ge=1, le=100)],
    search: Annotated[
        str | None,
        Query(None, description="Search by user or repo URI (partial match)"),
    ],
    status: Annotated[str | None, Query(None)],
) -> PaginatedSessionsResponse:
    offset = (page - 1) * page_size
    items, total = await DatabaseService.list_sessions(
        search=search,
        status=status,
        offset=offset,
        limit=page_size,
    )

    return PaginatedSessionsResponse(
        items=[SessionSummaryResponse.from_row(s) for s in items],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=math.ceil(total / page_size) if total > 0 else 0,
    )


@router.get(
    "/sessions/{session_id}",
    summary="Get session detail with operations timeline",
)
async def get_session_detail(session_id: str) -> SessionDetailResponse:
    user_session = await DatabaseService.get_session(session_id)
    if not user_session:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    operations = await DatabaseService.get_operations(session_id)

    return SessionDetailResponse(
        session=SessionSummaryResponse.from_row(user_session),
        operations=[
            OperationResponse.model_validate(op, from_attributes=True)
            for op in operations
        ],
    )


@router.patch(
    "/sessions/{session_id}/apply_allowed",
    summary="Toggle apply_allowed for a session (admin unlock/lock)",
)
async def toggle_apply_allowed(
    session_id: str,
    allowed: bool = Body(..., embed=True),
) -> dict:
    user_session = await DatabaseService.get_session(session_id)
    if not user_session:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    await DatabaseService.toggle_apply_allowed(session_id, allowed)

    return {"session_id": session_id, "apply_allowed": allowed}
