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
from src.shared.config import system_config
from src.shared.constants import SessionStatus
from src.shared.exceptions import ExceptionHandler
from src.shared.logger import logging

router = APIRouter(
    prefix="/events",
    tags=["Events Subscription"],
)


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
    - Automatically terminates when session reaches COMPLETED or FAILED status
    - Closes stream when max iterations reached (session is preserved)
    - Messages are sanitized by removing double quotes to prevent JSON parsing issues

    Note:
    - Connection remains open until session completion or failure
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

            payload = {
                "status_msg": session_status.status.name,
                "detail": {
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
