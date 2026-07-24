# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query

from src.domains.dto import PaginatedSessionOverview, SessionOverview
from src.domains.services.database_service import DatabaseService
from src.shared.exceptions import ExceptionHandler

router = APIRouter(prefix="/sessions", tags=["Session Management"])


@router.get(
    path="",
    summary="Retrive user sessions.",
)
async def sessions_list(
    username: Annotated[str, Query(min_length=3, max_length=40)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> PaginatedSessionOverview:
    """TODO"""
    try:
        session = await DatabaseService.list_sessions(
            user_id=username,
            offset=(page - 1) * page_size,
            limit=page_size,
        )
    except ExceptionHandler as e:
        raise HTTPException(status_code=e.error_code, detail=e.message)
    return session


@router.get(
    path="/{session_id}",
    summary="Get the corresponding session related data",
)
async def session_status(
    session_id: Annotated[
        str,
        Path(pattern="[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"),
    ],
) -> SessionOverview:
    """Retrieve the final payload data from a completed session.

    This endpoint returns the complete session payload once the session has finished
    processing. It's designed to be called after the SSE stream has indicated
    completion to retrieve the final results.

    Note:
    - This endpoint should only be called after the session has completed
    - The payload will be None until the session finishes processing
    - Session data persists until explicitly deleted via the unsubscribe endpoint
    """
    try:
        session = await DatabaseService.get_session_overview(session_id)
    except ExceptionHandler as e:
        raise HTTPException(status_code=e.error_code, detail=e.message)

    return session


#
#
# @router.delete(
#     path="/unsubscribe/{session_id}",
#     status_code=204,
#     summary="Delete session data",
#     responses={
#         204: {"description": "The session has been successfully deleted"},
#         404: {
#             "description": "The requested content has already been permanently deleted from server, "
#             + "with no forwarding address",
#             "content": {
#                 "application/json": {
#                     "example": {"detail": "Session id 1234 not found."}
#                 }
#             },
#         },
#     },
# )
# def session_delete(
#     session_id: Annotated[
#         str,
#         Path(pattern="[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"),
#     ],
# ):
#     """Delete session data and cleanup resources.
#
#     This endpoint permanently removes a session and all associated data from the server.
#     It's typically called when the client no longer needs the session or wants to
#     cleanup resources after retrieving the final payload.
#
#     Note:
#     - This operation is irreversible - all session data will be permanently lost
#     - Session cleanup is also triggered automatically when max iterations are reached
#       in the SSE subscription endpoint
#     """
#     get_session(session_id).delete()
