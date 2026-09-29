# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from src.api.deps import assert_session_access, get_current_user
from src.domains.dto import PaginatedSessionSummary, SessionDetail
from src.domains.entities import User
from src.domains.services.database_service import DatabaseService
from src.shared.constants import OperationType, SessionStatus
from src.shared.exceptions import ExceptionHandler

router = APIRouter(prefix="/sessions", tags=["Session Management"])


@router.get(
    path="/list",
    summary="List the caller's sessions.",
)
async def sessions_list(
    user: Annotated[User, Depends(get_current_user)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    operation: Annotated[OperationType | None, Query()] = None,
    status: Annotated[SessionStatus | None, Query()] = None,
    search: Annotated[str | None, Query(max_length=200)] = None,
) -> PaginatedSessionSummary:
    """Paginated session summaries for the sessions table.

    Always scoped to the authenticated caller's own sessions. Each item
    carries the operation, terraform provider, first query, workspace
    URI, latest status, and lock flags — everything the list view
    renders, resolved server-side. ``status`` matches a session's most
    recent status; ``search`` matches first query, workspace URI, or
    session id.
    """
    try:
        return await DatabaseService.list_sessions(
            user_pk=user.id,
            operation=operation,
            status=status,
            search=search,
            offset=(page - 1) * page_size,
            limit=page_size,
        )
    except ExceptionHandler as e:
        raise HTTPException(status_code=e.error_code, detail=e.message)


@router.get(
    path="",
    summary="Get the full session aggregate.",
    responses={404: {"description": "Unknown session."}},
)
async def session_detail(
    session_id: Annotated[UUID, Query(alias="id")],
    user: Annotated[User, Depends(get_current_user)],
    include_history: Annotated[
        bool,
        Query(description="Include the session's serialized conversation history."),
    ] = False,
) -> SessionDetail:
    """The complete read model for the session detail view.

    Returns the session facts (workspace, provider, first query) and one
    entry per generation round containing its statuses, pull requests,
    and artifacts (reports, plans, code changes) with client-fetchable
    URLs. The session's timeline is the rounds' statuses concatenated in
    round order; ``current_status`` carries the latest one.

    Pass ``include_history=true`` to also populate ``history`` with the
    session's conversation turns (``[{"user": ..., "assistant": ...}]``);
    this variant always reads fresh from the database, so keep status
    polls on the default.

    Clients subscribed to the push channel should refetch this endpoint
    whenever a `session.updated` nudge arrives for this session id.
    """
    await assert_session_access(user, session_id, write=False)
    try:
        return await DatabaseService.get_session_detail(
            session_id, include_history=include_history
        )
    except ExceptionHandler as e:
        raise HTTPException(status_code=e.error_code, detail=e.message)
