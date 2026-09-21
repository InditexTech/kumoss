# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import json
from asyncio import sleep
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.params import Path
from fastapi.responses import StreamingResponse

from src.api.deps import assert_session_access, get_current_user
from src.domains.entities import User
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
    summary="Subscribe to a session's progress events over SSE",
    responses={
        200: {
            "description": "Stream of session status events.",
            "content": {
                "text/event-stream": {
                    "schema": {"type": "string"},
                    "example": (
                        'data: {"status_msg": "GENERATING",'
                        ' "detail": {"message": "..."}}\n\n'
                    ),
                }
            },
        }
    },
)
async def subscribe_events(
    session_id: Annotated[
        UUID,
        Path(description="session id to subscribe to server sent events"),
    ],
    user: Annotated[User, Depends(get_current_user)],
):
    """Subscribe to a stream of message events through Server-Sent Events (SSE).

    This endpoint establishes a persistent connection that streams real-time updates
    about a session's progress. It uses the SSE protocol to send JSON-formatted
    messages containing session status and details.

    Behavior:
    - Polls the session message queue every 5 seconds
    - Automatically terminates when session reaches a terminal status:
      COMPLETED, UNCOMPLETED (rejected round) or FAILED
    - Closes stream when max iterations reached (session is preserved)
    - Messages are sanitized by removing double quotes to prevent JSON parsing issues

    Note:
    - Connection remains open until the session completes, is rejected or fails
    """

    async def event_stream():
        i = 0
        yield ": keepalive\n\n"
        for _ in range(system_config.orchestration.max_session_events_iteration):
            i += 1
            try:
                status: Status = await DatabaseService.get_last_status(session_id)
            except ExceptionHandler as e:
                logging.error(e.message)
                await sleep(4)
                continue

            payload = {
                "status_msg": status.status.name,
                "detail": {
                    "message": status.msg.replace('"', ""),  # Sanitize msg
                },
            }

            yield f"data: {json.dumps(payload)}\n\n"

            if status.status == SessionStatus.FAILED:
                logging.error(
                    f"SSE session failed, closing stream. session_id={session_id}"
                )
                return
            if status.status in (
                SessionStatus.COMPLETED,
                SessionStatus.UNCOMPLETED,
            ):
                logging.info(
                    f"SSE session {status.status.value}, closing stream. session_id={session_id}"
                )
                return

            await sleep(5)

    await assert_session_access(user, session_id, write=False)
    await sleep(2)
    try:
        _ = await DatabaseService.get_session_summary(session_id)
    except ExceptionHandler as e:
        raise HTTPException(status_code=e.error_code, detail=e.message)
    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
