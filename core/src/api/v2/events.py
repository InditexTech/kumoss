# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import json
from uuid import UUID
from asyncio import sleep
from typing import Annotated

from fastapi import APIRouter, HTTPException
from fastapi.params import Path
from fastapi.responses import StreamingResponse

from src.domains.entities import Session
from src.domains.services import SessionService
from src.domains.dto import SessionPayloadDTO
from src.application.factory import HandlerFactory
from src.shared.config import system_config
from src.shared.constants import SessionStatus, LLMProvider
from src.shared.exceptions import ExceptionHandler
from src.shared.logger import logging

router = APIRouter(
    prefix="/events",
    tags=["Events Subscription"],
)

_LLM_ADAPTER = HandlerFactory.get_llm_adapter(LLMProvider.GEMINI_FLASH_LITE, 0.7)


@router.get(
    path="/subscribe/{session_id}",
    summary="Subscribe to a stream of message events through SSE",
)
async def subscribe_events(
    session_id: Annotated[
        str,
        Path(
            description="session id to subscribe to server sent events",
            pattern="[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
        ),
    ],
):
    """Subscribe to a stream of message events through Server-Sent Events (SSE).

    This endpoint establishes a persistent connection that streams real-time updates
    about a session's progress. It uses the SSE protocol to send JSON-formatted
    messages containing session status and details.

    Behavior:
    - Polls the session message queue every 5 seconds
    - Falls back to LLM-generated messages when queue is empty (10s interval)
    - Automatically terminates when session reaches COMPLETED or FAILED status
    - Closes stream when max iterations reached (session is preserved)
    - Messages are sanitized by removing double quotes to prevent JSON parsing issues

    Note:
    - Connection remains open until session completion or failure
    - Uses a small LLM provider for fallback messages
    """
    session: Session = get_session(session_id)

    async def event_stream():
        i = 0
        await sleep(10)  # Wait for acknowledge message
        while True:
            if i == system_config.orchestration.max_session_events_iteration:
                logging.warning(
                    f"SSE max iterations reached, closing stream. session_id={session_id}"
                )
                break
            i += 1
            session_status = session.status

            # Don't send payload to client as it breaks JSON parsing
            payload = {
                "status_msg": session_status.status.name,
                "detail": {
                    "validation_id": session.validation_id,
                    "message": session_status.message.replace('"', ""),  # Sanitize msg
                },
            }

            yield f"data: {json.dumps(payload)}\n\n"

            if (
                session_status.status == SessionStatus.COMPLETED
                or session_status.status == SessionStatus.FAILED
            ):
                break

            await sleep(5)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get(
    path="/get/{session_id}",
    summary="Get the corresponding session related data once the session has finished",
    responses={
        200: {
            "description": "Get the main response to the query, plus client session state data.",
        },
        404: {
            "description": "The server cannot find the requested resource.",
            "content": {
                "application/json": {
                    "example": {"detail": "Session id 1234 does not exist."}
                }
            },
        },
        409: {
            "description": "The request conflicts with the current state of the server",
            "content": {
                "application/json": {
                    "example": {"detail": "Session id 1234 has not yet finished."}
                }
            },
        },
    },
)
def session_payload(
    session_id: Annotated[
        str,
        Path(pattern="[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"),
    ],
) -> SessionPayloadDTO:
    """Retrieve the final payload data from a completed session.

    This endpoint returns the complete session payload once the session has finished
    processing. It's designed to be called after the SSE stream has indicated
    completion to retrieve the final results.

    Note:
    - This endpoint should only be called after the session has completed
    - The payload will be None until the session finishes processing
    - Session data persists until explicitly deleted via the unsubscribe endpoint
    """
    session = get_session(session_id)
    if not session.payload:
        raise HTTPException(
            status_code=409, detail=f"Session is still in progress. id={session.id}"
        )
    return session.payload


@router.delete(
    path="/unsubscribe/{session_id}",
    status_code=204,
    summary="Delete session data",
    responses={
        204: {"description": "The session has been successfully deleted"},
        404: {
            "description": "The requested content has already been permanently deleted from server, "
            "with no forwarding address",
            "content": {
                "application/json": {
                    "example": {"detail": "Session id 1234 not found."}
                }
            },
        },
    },
)
def session_delete(
    session_id: Annotated[
        str,
        Path(pattern="[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"),
    ],
):
    """Delete session data and cleanup resources.

    This endpoint permanently removes a session and all associated data from the server.
    It's typically called when the client no longer needs the session or wants to
    cleanup resources after retrieving the final payload.

    Note:
    - This operation is irreversible - all session data will be permanently lost
    - Session cleanup is also triggered automatically when max iterations are reached
      in the SSE subscription endpoint
    """
    get_session(session_id).delete()


def get_session(session_id: str) -> Session:
    try:
        session_uuid = UUID(session_id.strip('"'))
        return SessionService.get_session(session_uuid)
    except ValueError as e:
        raise HTTPException(
            detail=f"Error: invalid session UUID. {e}",
            status_code=400,
        )
    except ExceptionHandler as e:
        raise HTTPException(
            detail=e.message,
            status_code=e.error_code,
        )
