# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""User-originated notifications.

Lets the web client submit a notification (today: the support request
typed into the header's chat-bubble modal and the "Contact team" button)
that the core forwards to the notifications service defined in
`contracts/openapi/notifications.v1.yaml`.

The caller must be authenticated; any signed-in user may notify. The
audience is derived server-side (panel editors and above plus the caller)
so the browser cannot pick recipients. Unlike the pipeline's best-effort
notifications, this route tells the caller when nothing was delivered.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from src.api.deps import CurrentUser, get_current_user
from src.api.dtos import NotificationAcceptedResponse, SubmitNotificationRequest
from src.clients.notifications.models.notification_request_severity import (
    NotificationRequestSeverity,
)
from src.infrastructure.external.notification_service import NotificationServiceClient
from src.shared.config.system_config import system_config

router = APIRouter(prefix="/notifications", tags=["Notifications"])


@router.post(
    path="",
    status_code=202,
    response_model=NotificationAcceptedResponse,
    summary="Submit a notification for delivery through the notifications service.",
    responses={
        202: {"description": "Notification accepted by the notifications service."},
        502: {"description": "The notifications service did not deliver it."},
        503: {"description": "The notifications service is disabled."},
    },
)
async def submit_notification(
    notification: SubmitNotificationRequest,
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> NotificationAcceptedResponse:
    if not system_config.services.notifications.enabled:
        raise HTTPException(status_code=503, detail="Notifications are disabled.")
    delivery_id = await NotificationServiceClient.notify(
        kind=notification.kind,
        severity=NotificationRequestSeverity(notification.severity),
        subject=notification.subject,
        body=notification.body,
        audience=await NotificationServiceClient.recipients(user.email),
        links=[(link.label, str(link.url)) for link in notification.links] or None,
        context=notification.context or None,
    )
    if delivery_id is None:
        raise HTTPException(status_code=502, detail="Notification was not delivered.")
    return NotificationAcceptedResponse(delivery_id=delivery_id)
