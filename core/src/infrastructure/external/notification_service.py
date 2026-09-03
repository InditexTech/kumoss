# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Notifications microservice client used by core.

Wraps the generated `src.clients.notifications` HTTP client behind a
small, async-friendly facade. Mirrors the pattern used by
`MappingServiceClient`: read endpoint+token from system_config,
construct a fresh `AuthenticatedClient` per call, and no-op when the
service is disabled or unconfigured.

Unlike mapping/authz, notifications are fire-and-forget side effects:
a failed send must never fail the calling pipeline, so `notify`
swallows every error and logs a warning instead of raising.

Surface:

- `NotificationServiceClient.notify(kind, severity, subject, body)` —
  generic primitive.
- `NotificationServiceClient.notify_compliance_failure(session_id,
  summary)` — semantic helper owning the `iac.compliance.check_failed`
  kind and message format. Add one such helper per notification kind
  so kind strings and formatting stay centralized here.
"""

from __future__ import annotations

from uuid import UUID

import httpx

from src.clients.notifications.api.notify import notify as notify_op
from src.clients.notifications.client import AuthenticatedClient
from src.clients.notifications.models.notification_accepted import (
    NotificationAccepted,
)
from src.clients.notifications.models.notification_request import NotificationRequest
from src.clients.notifications.models.notification_request_severity import (
    NotificationRequestSeverity,
)
from src.shared.config import system_config
from src.shared.logger import logging


class NotificationServiceClient:
    """Stateless static client for the notifications microservice."""

    @staticmethod
    async def notify(
        *,
        kind: str,
        severity: NotificationRequestSeverity,
        subject: str,
        body: str,
    ) -> None:
        """Send a notification, best-effort.

        No-ops when the service is disabled or unconfigured. On any
        failure (timeout, unreachable, rejected request) logs a warning
        and returns — never raises.
        """
        cfg = system_config.services.notifications
        if not cfg.enabled or not cfg.endpoint:
            return

        client = AuthenticatedClient(
            base_url=cfg.endpoint,
            token=cfg.token,
            timeout=httpx.Timeout(cfg.timeout),
        )
        try:
            async with client as c:
                response = await notify_op.asyncio(
                    client=c,
                    body=NotificationRequest(
                        kind=kind,
                        severity=severity,
                        subject=subject,
                        body=body,
                    ),
                )
            if not isinstance(response, NotificationAccepted):
                logging.warning(
                    f"Notifications service rejected '{kind}' ({subject}): {response!r}"
                )
        except Exception as e:
            logging.warning(f"Failed to send '{kind}' notification ({subject}): {e}")

    @staticmethod
    async def notify_compliance_failure(session_id: UUID, summary: str) -> None:
        await NotificationServiceClient.notify(
            kind="iac.compliance.check_failed",
            severity=NotificationRequestSeverity.WARNING,
            subject=f"Compliance check failed – session {session_id}",
            body=summary,
        )

    @staticmethod
    async def notify_exception_failure(session_id: UUID, summary: str) -> None:
        await NotificationServiceClient.notify(
            kind="system.exception.failure",
            severity=NotificationRequestSeverity.ERROR,
            subject=f"System Core exception failure – session {session_id}",
            body=summary,
        )

    @staticmethod
    async def notify_apply_failure(session_id: UUID, summary: str) -> None:
        await NotificationServiceClient.notify(
            kind="iac.apply.failure",
            severity=NotificationRequestSeverity.ERROR,
            subject=f"Infrastructure deployment failure – session {session_id}",
            body=summary,
        )
