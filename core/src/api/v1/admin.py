# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import math
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from src.api.deps import CurrentUser, require_panel_role
from src.api.dtos import (
    AdminUserEntry,
    ApplyAllowedResponse,
    PaginatedUsers,
    UpdateUserRolesRequest,
)
from src.domains.dto import PaginatedSessionSummary, SessionDetail
from src.domains.services.database_service import DatabaseService
from src.domains.services.user_service import UserService
from src.infrastructure.database.models import User
from src.shared.constants import OperationType, PanelRole, SessionStatus
from src.shared.exceptions import ExceptionHandler

router = APIRouter(
    prefix="/admin",
    tags=["Admin"],
    dependencies=[Depends(require_panel_role(PanelRole.VIEWER))],
)


def _user_entry(user: User) -> AdminUserEntry:
    return AdminUserEntry(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        operation_role=user.operation_role,
        panel_role=user.panel_role,
        issuer=user.issuer,
        subject=user.subject,
        created_at=user.created_at,
    )


@router.get(
    path="/sessions",
    summary="List sessions across all users.",
)
async def admin_sessions_list(
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    operation: Annotated[OperationType | None, Query()] = None,
    status: Annotated[SessionStatus | None, Query()] = None,
    search: Annotated[str | None, Query(max_length=200)] = None,
    user_email: Annotated[str | None, Query(max_length=254)] = None,
) -> PaginatedSessionSummary:
    """Cross-user paginated session summaries for the admin panel.

    Same filter surface as the user-facing list plus ``user_email``,
    which partial-matches the owning user's email.
    """
    try:
        return await DatabaseService.list_sessions(
            user_pk=None,
            operation=operation,
            status=status,
            search=search,
            user_email=user_email,
            offset=(page - 1) * page_size,
            limit=page_size,
        )
    except ExceptionHandler as e:
        raise HTTPException(status_code=e.error_code, detail=e.message)


@router.get(
    path="/sessions/{session_id}",
    summary="Get any session's full aggregate.",
    responses={404: {"description": "Unknown session."}},
)
async def admin_session_detail(
    session_id: UUID,
    include_history: Annotated[
        bool,
        Query(description="Include the session's serialized conversation history."),
    ] = False,
) -> SessionDetail:
    try:
        return await DatabaseService.get_session_detail(
            session_id, include_history=include_history
        )
    except ExceptionHandler as e:
        raise HTTPException(status_code=e.error_code, detail=e.message)


@router.patch(
    path="/sessions/{session_id}/apply_allowed",
    summary="Toggle whether a session's plan may be applied (lock/unlock).",
    dependencies=[Depends(require_panel_role(PanelRole.EDITOR))],
    responses={404: {"description": "Unknown session."}},
)
async def toggle_apply_allowed(
    session_id: UUID,
    allowed: Annotated[
        bool,
        Body(description="True unlocks apply/merge; false blocks them.", embed=True),
    ],
) -> ApplyAllowedResponse:
    updated = await DatabaseService.set_lock(session_id, lock=not allowed)
    if not updated:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found.")
    return ApplyAllowedResponse(uuid=session_id, apply_allowed=allowed)


@router.get(
    path="/users",
    summary="List internal users with their roles.",
    dependencies=[Depends(require_panel_role(PanelRole.ADMIN))],
)
async def admin_users_list(
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    search: Annotated[
        str | None,
        Query(max_length=254, description="Partial match on email or display name."),
    ] = None,
) -> PaginatedUsers:
    users, total = await UserService.list_users(
        offset=(page - 1) * page_size,
        limit=page_size,
        search=search,
    )
    return PaginatedUsers(
        items=[_user_entry(u) for u in users],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=math.ceil(total / page_size) if total > 0 else 0,
    )


@router.put(
    path="/users/{user_id}/roles",
    summary="Set a user's roles (full-state assignment).",
    responses={
        404: {"description": "Unknown user."},
        409: {"description": "A panel admin cannot drop their own admin role."},
    },
)
async def set_user_roles(
    user_id: int,
    request: UpdateUserRolesRequest,
    caller: Annotated[CurrentUser, Depends(require_panel_role(PanelRole.ADMIN))],
) -> AdminUserEntry:
    if caller.id == user_id and request.panel_role is not PanelRole.ADMIN:
        raise HTTPException(
            status_code=409,
            detail="A panel admin cannot remove their own admin role.",
        )
    try:
        user = await UserService.set_roles(
            user_id,
            operation_role=request.operation_role,
            panel_role=request.panel_role,
        )
    except ExceptionHandler as e:
        raise HTTPException(status_code=e.error_code, detail=e.message)
    return _user_entry(user)
