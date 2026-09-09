# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Notifications service client used by core.

Wraps the generated `src.clients.notifications` HTTP client behind a
small, async-friendly facade. Mirrors the pattern used by
`MappingServiceClient`: read endpoint+token from system_config and
construct a fresh `AuthenticatedClient` per call.

Nothing in this module raises. A notification is a side effect of a
session, never a reason for it to fail: every entry point logs a warning
and returns `None` when the service is disabled, unreachable, or rejects
the request.

The semantic helpers (`notify_compliance_failure`, ...) own one `kind`
string and message format each so kind strings stay centralized here.
They take the session id and the owner's email; the summary already
carries the context of the problem. The audience is the owner plus every
user holding a panel role of editor or above.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import httpx

from src.clients.notifications.api.notify import notify as notify_op
from src.clients.notifications.client import AuthenticatedClient
from src.clients.notifications.models.link import Link
from src.clients.notifications.models.notification_accepted import (
    NotificationAccepted,
)
from src.clients.notifications.models.notification_request import NotificationRequest
from src.clients.notifications.models.notification_request_context import (
    NotificationRequestContext,
)
from src.clients.notifications.models.notification_request_severity import (
    NotificationRequestSeverity,
)
from src.clients.notifications.types import UNSET
from src.domains.services.user_service import UserService
from src.shared.config import system_config
from src.shared.constants import PanelRole
from src.shared.logger import logging


class NotificationServiceClient:
    """Stateless static client for the notifications service."""

    @staticmethod
    def enabled() -> bool:
        """True when the core is configured to talk to a notifications service.

        Every public entry point checks this first so a disabled service is
        never contacted — not even indirectly through the recipients lookup.
        """
        cfg = system_config.services.notifications
        return bool(cfg.enabled and cfg.endpoint)

    @staticmethod
    async def recipients(owner_email: str | None) -> list[str]:
        """Panel editors and above, plus the session owner, deduplicated.

        Falls back to the owner alone when the users store cannot be read
        so a notification still goes out.
        """
        try:
            staff = await UserService.emails_with_panel_role(PanelRole.EDITOR)
        except Exception as e:
            logging.warning(f"Failed to resolve notification recipients: {e}")
            staff = []
        return sorted({*staff, *([owner_email] if owner_email else [])})

    @staticmethod
    async def notify(
        *,
        kind: str,
        severity: NotificationRequestSeverity,
        subject: str,
        body: str,
        audience: list[str],
        links: list[tuple[str, str]] | None = None,
        context: dict[str, Any] | None = None,
    ) -> UUID | None:
        """Submit a notification; return its delivery id, or None.

        `links` are `(label, url)` pairs. Returns None without raising when
        the service is disabled or unconfigured, times out, is unreachable,
        or answers with anything but an acceptance.
        """
        if not NotificationServiceClient.enabled():
            return None
        cfg = system_config.services.notifications

        ctx = UNSET
        if context:
            ctx = NotificationRequestContext()
            ctx.additional_properties = dict(context)
        request = NotificationRequest(
            kind=kind,
            severity=severity,
            subject=subject,
            body=body,
            audience=audience,
            links=[Link(label=label, url=url) for label, url in links]
            if links
            else UNSET,
            context=ctx,
        )
        client = AuthenticatedClient(
            base_url=cfg.endpoint,
            token=cfg.token,
            timeout=httpx.Timeout(cfg.timeout),
        )
        try:
            async with client as c:
                response = await notify_op.asyncio(client=c, body=request)
        except Exception as e:
            logging.warning(f"Failed to send '{kind}' notification ({subject}): {e}")
            return None

        if isinstance(response, NotificationAccepted):
            return response.delivery_id
        logging.warning(
            f"Notifications service rejected '{kind}' ({subject}): {response!r}"
        )
        return None

    @staticmethod
    async def notify_compliance_failure(
        session_id: UUID, owner_email: str, summary: str
    ) -> None:
        if not NotificationServiceClient.enabled():
            return
        _ = await NotificationServiceClient.notify(
            kind="iac.compliance.check_failed",
            severity=NotificationRequestSeverity.WARNING,
            subject=f"Compliance check failed – session {session_id}",
            body=summary,
            audience=await NotificationServiceClient.recipients(owner_email),
        )

    @staticmethod
    async def notify_exception_failure(
        session_id: UUID, owner_email: str, summary: str
    ) -> None:
        if not NotificationServiceClient.enabled():
            return
        _ = await NotificationServiceClient.notify(
            kind="system.exception.failure",
            severity=NotificationRequestSeverity.ERROR,
            subject=f"System Core exception failure – session {session_id}",
            body=summary,
            audience=await NotificationServiceClient.recipients(owner_email),
        )

    @staticmethod
    async def notify_apply_failure(
        session_id: UUID, owner_email: str, summary: str
    ) -> None:
        if not NotificationServiceClient.enabled():
            return
        _ = await NotificationServiceClient.notify(
            kind="iac.apply.failure",
            severity=NotificationRequestSeverity.ERROR,
            subject=f"Infrastructure deployment failure – session {session_id}",
            body=summary,
            audience=await NotificationServiceClient.recipients(owner_email),
        )
