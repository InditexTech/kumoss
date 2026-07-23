# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import json
from asyncio import sleep
from typing import Annotated

from fastapi import APIRouter
from fastapi.params import Path
from fastapi.responses import StreamingResponse

from src.domains.value_objects import Status
from src.domains.services.database_service import DatabaseService
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

    async def event_stream():
        i = 0
        await sleep(10)  # Wait for acknowledge message
        while True:
            i += 1
            try:
                status: Status = await DatabaseService.get_last_status(session_id)
            except ExceptionHandler as e:
                logging.error(e.message)
                await sleep(5)
                continue

            if i == system_config.orchestration.max_session_events_iteration:
                logging.error(
                    f"SSE max iterations reached, closing stream. session_id={session_id}"
                )
                break

            payload = {
                "status_msg": status.status,
                "detail": {
                    "message": status.msg.replace('"', ""),  # Sanitize msg
                },
            }

            yield f"data: {json.dumps(payload)}\n\n"  # FIXME

            if (
                status.status == SessionStatus.COMPLETED
                or status.status == SessionStatus.FAILED
            ):
                break

            await sleep(5)

    return StreamingResponse(event_stream(), media_type="text/event-stream")
