# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""FastAPI application for the notifications reference implementation."""

from __future__ import annotations

from contextlib import asynccontextmanager
from uuid import uuid4

import httpx
from fastapi import FastAPI, Header, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .auth import verify_bearer_token
from .config import Config
from .models import Health, NotificationAccepted, NotificationRequest, Problem
from .slack import deliver


config = Config.from_env()


@asynccontextmanager
async def lifespan(app: FastAPI):
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

    if not config.slack_webhook_url:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Notifications service is running but no SLACK_WEBHOOK_URL is configured.",
        )

    try:
        await deliver(body, config.slack_webhook_url, request.app.state.http)
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Slack delivery failed: {exc}",
        ) from exc

    return NotificationAccepted(delivery_id=uuid4())
