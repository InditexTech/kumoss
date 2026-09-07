# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Notifications microservice client used by core.

Wraps the generated `src.clients.notifications` HTTP client behind a
small, async-friendly facade. Mirrors the pattern used by
`MappingServiceClient`: read endpoint+token from system_config and
construct a fresh `AuthenticatedClient` per call.

Two entry points with deliberately different failure semantics:

- `NotificationServiceClient.send(...)` — request/response. Raises
  `ExceptionHandler` when the service is disabled/unconfigured (503),
  times out (504), is unreachable or rejects the request (502, or the
  sidecar's own 503 when it has no channel configured). Used by the
  browser-facing `POST /v1/notifications` route, where the caller must
  learn that nothing was delivered.
- `NotificationServiceClient.notify(...)` — fire-and-forget. Wraps
  `send`, swallows every error and logs a warning. Used by the pipeline
  handlers, where a failed side effect must never fail the run.

Semantic helpers (`notify_compliance_failure`, ...) own one `kind`
string and message format each so kind strings stay centralized here.
They take the `SessionContext` and attach its identifying metadata
(session id, operation, repository, branch, IaC path, cloud, the user's
request) as `context`, which the sidecar renders as fields.
"""

from __future__ import annotations

from typing import Any

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
from src.clients.notifications.models.problem import Problem
from src.clients.notifications.types import UNSET, Unset
from src.domains.entities.session import SessionContext
from src.shared.config import system_config
from src.shared.exceptions import ExceptionHandler
from src.shared.logger import logging


class NotificationServiceClient:
    """Stateless static client for the notifications microservice."""

    @staticmethod
    def _build_request(
        *,
        kind: str,
        severity: NotificationRequestSeverity,
        subject: str,
        body: str,
        audience: list[str] | None,
        links: list[tuple[str, str]] | None,
        context: dict[str, Any] | None,
    ) -> NotificationRequest:
        ctx: NotificationRequestContext | Unset = UNSET
        if context:
            ctx = NotificationRequestContext()
            ctx.additional_properties = dict(context)
        return NotificationRequest(
            kind=kind,
            severity=severity,
            subject=subject,
            body=body,
            audience=list(audience) if audience else UNSET,
            links=[Link(label=label, url=url) for label, url in links]
            if links
            else UNSET,
            context=ctx,
        )

    @staticmethod
    async def send(
        *,
        kind: str,
        severity: NotificationRequestSeverity,
        subject: str,
        body: str,
        audience: list[str] | None = None,
        links: list[tuple[str, str]] | None = None,
        context: dict[str, Any] | None = None,
    ) -> NotificationAccepted:
        """Submit a notification and return the sidecar's acceptance.

        `links` are `(label, url)` pairs. Raises `ExceptionHandler`:
        503 when the service is disabled/unconfigured in system config or
        the sidecar reports it has no channel configured, 504 on timeout,
        502 when unreachable or when the sidecar rejects the request.
        """
        cfg = system_config.services.notifications
        if not cfg.enabled or not cfg.endpoint:
            raise ExceptionHandler(
                "notifications service is disabled or has no endpoint configured",
                503,
            )

        request = NotificationServiceClient._build_request(
            kind=kind,
            severity=severity,
            subject=subject,
            body=body,
            audience=audience,
            links=links,
            context=context,
        )
        client = AuthenticatedClient(
            base_url=cfg.endpoint,
            token=cfg.token,
            timeout=httpx.Timeout(cfg.timeout),
        )
        logging.info(f"sending '{kind}' notification to {cfg.endpoint} ({subject})")
        try:
            async with client as c:
                response = await notify_op.asyncio(client=c, body=request)
        except httpx.TimeoutException as e:
            raise ExceptionHandler(f"notifications service timed out: {e}", 504) from e
        except httpx.RequestError as e:
            raise ExceptionHandler(
                f"notifications service unreachable: {e}", 502
            ) from e

        if isinstance(response, NotificationAccepted):
            logging.info(
                f"notifications service accepted '{kind}' "
                + f"(delivery_id={response.delivery_id})"
            )
            return response
        if isinstance(response, Problem):
            detail = response.detail if not isinstance(response.detail, Unset) else ""
            reason = detail or response.title
            # The sidecar's "running but not configured" is the only
            # upstream status worth relaying verbatim: it tells the user
            # the operator has not wired a channel. Everything else
            # (401/403 token mismatch, 422, 502) is a core↔sidecar
            # problem the browser cannot act on.
            code = 503 if response.status == 503 else 502
            raise ExceptionHandler(f"notifications service rejected: {reason}", code)
        raise ExceptionHandler(
            f"notifications service returned an unexpected response: {response!r}",
            502,
        )

    @staticmethod
    async def notify(
        *,
        kind: str,
        severity: NotificationRequestSeverity,
        subject: str,
        body: str,
        audience: list[str] | None = None,
        links: list[tuple[str, str]] | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        """Send a notification, best-effort.

        No-ops when the service is disabled or unconfigured. On any
        failure (timeout, unreachable, rejected request) logs a warning
        and returns — never raises.
        """
        cfg = system_config.services.notifications
        if not cfg.enabled or not cfg.endpoint:
            return
        try:
            _ = await NotificationServiceClient.send(
                kind=kind,
                severity=severity,
                subject=subject,
                body=body,
                audience=audience,
                links=links,
                context=context,
            )
        except Exception as e:
            logging.warning(f"Failed to send '{kind}' notification ({subject}): {e}")

    @staticmethod
    def session_metadata(ctx: SessionContext) -> dict[str, Any]:
        """Identifying metadata for a session, for `NotificationRequest.context`.

        Values are plain JSON types. The user's original request is the
        first user turn of the history, when it is a plain string.
        """
        request: str | None = None
        for turn in ctx.history:
            if isinstance(turn.user, str) and turn.user.strip():
                request = turn.user.strip()
                break
        return {
            "session_id": str(ctx.id),
            "operation": ctx.operation.name.lower(),
            "cloud": ctx.terraform_prv.value,
            "project": ctx.scope_id,
            "repository": ctx.repo_uri,
            "branch": ctx.branch_name,
            "iac_path": ctx.iac_path,
            "round": ctx.round_id,
            "user": ctx.user_id,
            "request": request,
        }

    @staticmethod
    async def notify_compliance_failure(ctx: SessionContext, summary: str) -> None:
        await NotificationServiceClient.notify(
            kind="iac.compliance.check_failed",
            severity=NotificationRequestSeverity.WARNING,
            subject=f"Compliance check failed – session {ctx.id}",
            body=summary,
            context=NotificationServiceClient.session_metadata(ctx),
        )

    @staticmethod
    async def notify_exception_failure(ctx: SessionContext, summary: str) -> None:
        await NotificationServiceClient.notify(
            kind="system.exception.failure",
            severity=NotificationRequestSeverity.ERROR,
            subject=f"System Core exception failure – session {ctx.id}",
            body=summary,
            context=NotificationServiceClient.session_metadata(ctx),
        )

    @staticmethod
    async def notify_apply_failure(ctx: SessionContext, summary: str) -> None:
        await NotificationServiceClient.notify(
            kind="iac.apply.failure",
            severity=NotificationRequestSeverity.ERROR,
            subject=f"Infrastructure deployment failure – session {ctx.id}",
            body=summary,
            context=NotificationServiceClient.session_metadata(ctx),
        )
