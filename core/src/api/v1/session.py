# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

# from typing import Annotated
#
# from fastapi import APIRouter, HTTPException
#
# from src.domains.services.database_service import DatabaseService
#
# router = APIRouter(prefix="/sessions", tags=["Session Management"])
#
#
# @router.get(
#     path="/get/{session_id}",
#     summary="Get the corresponding session related data",
#     responses={
#         200: {
#             "description": "Get the main response to the query, plus client session state data.",
#         },
#         404: {
#             "description": "The server cannot find the requested resource.",
#             "content": {
#                 "application/json": {
#                     "example": {"detail": "Session id 1234 does not exist."}
#                 }
#             },
#         },
#         409: {
#             "description": "The request conflicts with the current state of the server",
#             "content": {
#                 "application/json": {
#                     "example": {"detail": "Session id 1234 has not yet finished."}
#                 }
#             },
#         },
#     },
# )
# def session_status(
#     session_id: Annotated[
#         str,
#         Path(pattern="[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"),
#     ],
# ) -> SessionPayloadDTO:
#     """Retrieve the final payload data from a completed session.
#
#     This endpoint returns the complete session payload once the session has finished
#     processing. It's designed to be called after the SSE stream has indicated
#     completion to retrieve the final results.
#
#     Note:
#     - This endpoint should only be called after the session has completed
#     - The payload will be None until the session finishes processing
#     - Session data persists until explicitly deleted via the unsubscribe endpoint
#     """
#     session = get_session(session_id)
#     if not session.payload:
#         raise HTTPException(
#             status_code=409, detail=f"Session is still in progress. id={session.id}"
#         )
#     return session.payload
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

