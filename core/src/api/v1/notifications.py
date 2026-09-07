# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""User-originated notifications.

Lets the web client submit a notification (today: the support request
typed into the header's chat-bubble modal) that the core forwards to the
notifications microservice defined in
`contracts/openapi/notifications.v1.yaml`. The request body mirrors the
contract's `NotificationRequest` one-to-one so the client can speak the
contract vocabulary without knowing which channel is behind it.

Unlike the pipeline's fire-and-forget notifications, this route reports
delivery problems to the caller: 503 when no notifications service (or
no channel) is configured, 502/504 when the sidecar fails.
"""

from typing import Annotated, Any, ClassVar, Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from src.clients.notifications.models.notification_request_severity import (
    NotificationRequestSeverity,
)
from src.infrastructure.external.notification_service import NotificationServiceClient
from src.shared.exceptions import ExceptionHandler
from src.shared.logger import logging

router = APIRouter(prefix="/notifications", tags=["Notifications"])


class NotificationLink(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=128)
    url: HttpUrl = Field(max_length=2048)


class NotificationIn(BaseModel):
    """Mirror of the contract's `NotificationRequest` schema."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    kind: str = Field(
        min_length=1,
        max_length=128,
        description="Event category, dotted lowercase (e.g. support.user_question).",
    )
    severity: Literal["info", "warning", "error", "critical"]
    subject: str = Field(min_length=1, max_length=256)
    body: str = Field(min_length=1, max_length=16384)
    audience: list[Annotated[str, Field(min_length=1)]] = Field(
        default_factory=list, max_length=256
    )
    links: list[NotificationLink] = Field(default_factory=list, max_length=32)
    context: dict[str, Any] = Field(default_factory=dict)


@router.post(
    path="",
    status_code=202,
    summary="Submit a notification for delivery through the notifications service.",
    responses={
        202: {
            "description": "Notification accepted by the notifications service.",
            "content": {
                "application/json": {
                    "example": {"delivery_id": "8b5df7d0-c3dd-4db4-a93e-fdd5973be524"}
                }
            },
        },
        502: {"description": "The notifications service rejected the request."},
        503: {
            "description": "No notifications service (or delivery channel) is configured."
        },
        504: {"description": "The notifications service timed out."},
    },
)
async def submit_notification(notification: NotificationIn):
    try:
        accepted = await NotificationServiceClient.send(
            kind=notification.kind,
            severity=NotificationRequestSeverity(notification.severity),
            subject=notification.subject,
            body=notification.body,
            audience=notification.audience or None,
            links=[(link.label, str(link.url)) for link in notification.links] or None,
            context=notification.context or None,
        )
    except ExceptionHandler as e:
        logging.warning(
            f"POST /notifications '{notification.kind}' not delivered "
            + f"(HTTP {e.error_code}): {e.message}"
        )
        raise HTTPException(status_code=e.error_code, detail=e.message)
    return JSONResponse(
        status_code=202, content={"delivery_id": str(accepted.delivery_id)}
    )
