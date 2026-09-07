# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""FastAPI application for the notifications reference implementation."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from uuid import uuid4

import httpx
from fastapi import FastAPI, Header, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .auth import verify_bearer_token
from .config import Config
from .models import Health, NotificationAccepted, NotificationRequest, Problem
from .slack import DeliveryError, deliver


config = Config.from_env()
logger = logging.getLogger("nebula.notifications")


def configure_logging(level_name: str) -> None:
    """Route the service's own loggers to stdout at ``LOG_LEVEL``.

    uvicorn configures only its own loggers (``uvicorn.*``); records from
    ``nebula.notifications*`` would otherwise be dropped below WARNING.
    Applied to the ``nebula.notifications`` parent so the auth and slack
    child loggers inherit it, and idempotent so tests can re-import.
    """
    level = logging.getLevelNamesMapping().get(level_name, logging.INFO)
    root = logging.getLogger("nebula.notifications")
    root.setLevel(level)
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        root.addHandler(handler)
    root.propagate = False


configure_logging(config.log_level)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup summary: enough to diagnose "nothing arrives in Slack"
    # without ever printing the webhook URL or the token.
    logger.info(
        "notifications service ready: slack_webhook_configured=%s "
        "bearer_auth_enforced=%s log_level=%s",
        bool(config.slack_webhook_url),
        bool(config.expected_token),
        config.log_level,
    )
    if not config.slack_webhook_url:
        logger.warning(
            "SLACK_WEBHOOK_URL is empty: every POST /v1/notify will return 503 "
            "until it is set in services/notifications/.env"
        )
    if not config.expected_token:
        logger.warning(
            "NEBULA_NOTIFICATIONS_TOKEN is empty: accepting unauthenticated "
            "requests (local-dev mode)"
        )
    app.state.http = httpx.AsyncClient()
    try:
        yield
    finally:
        await app.state.http.aclose()


app = FastAPI(
    title="Nebula Notifications Service",
    version="1.0.0",
    description="Reference implementation of contracts/openapi/notifications.v1.yaml.",
    lifespan=lifespan,
)


def _problem(status_code: int, title: str, detail: str | None = None) -> JSONResponse:
    payload = Problem(
        type="about:blank", title=title, status=status_code, detail=detail
    ).model_dump(exclude_none=True)
    return JSONResponse(
        status_code=status_code,
        content=payload,
        media_type="application/problem+json",
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    return _problem(exc.status_code, exc.detail or "HTTP error")


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    # FastAPI's default 422 handler returns application/json; the contract
    # mandates application/problem+json for every error response.
    return _problem(422, "Request validation failed", str(exc))


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    return _problem(500, "Internal server error", str(exc))


@app.get("/healthz", response_model=Health, tags=["ops"])
async def healthz() -> Health:
    return Health(status="ok")


@app.post(
    "/v1/notify",
    response_model=NotificationAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["notify"],
)
async def notify(
    request: Request,
    body: NotificationRequest,
    authorization: str | None = Header(default=None),
) -> NotificationAccepted:
    verify_bearer_token(config, authorization)

    delivery_id = uuid4()
    logger.info(
        "delivery %s received: kind=%s severity=%s subject=%r audience=%d links=%d",
        delivery_id,
        body.kind,
        body.severity,
        body.subject[:80],
        len(body.audience),
        len(body.links),
    )

    if not config.slack_webhook_url:
        logger.warning(
            "delivery %s rejected: SLACK_WEBHOOK_URL is not configured", delivery_id
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Notifications service is running but no SLACK_WEBHOOK_URL is configured.",
        )

    try:
        slack_status = await deliver(
            body, config.slack_webhook_url, request.app.state.http
        )
    except DeliveryError as exc:
        # `exc.detail` is URL-free by construction (see slack.DeliveryError);
        # the raw httpx message would leak the webhook URL, which is the
        # Slack credential. Same rule for the log line.
        logger.warning(
            "delivery %s (kind=%s) failed: %s", delivery_id, body.kind, exc.detail
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Slack delivery failed: {exc.detail}",
        ) from exc

    logger.info("delivery %s delivered to slack (HTTP %d)", delivery_id, slack_status)
    return NotificationAccepted(delivery_id=delivery_id)
