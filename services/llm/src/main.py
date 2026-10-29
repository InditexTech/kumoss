# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""FastAPI application for the Kumoss LLM sidecar.

Owns the pieces of the core that have no Rust equivalent: the LiteLLM
Router (multi-provider completions), LiteLLM web search, and the
Playwright/Chromium + trafilatura page reads behind each search hit.
Implements contracts/openapi/llm.v1.yaml.

``config.yaml``'s ``llm`` and ``web_search`` sections are validated at
import time (missing provider credentials or a bad search provider stop
the process before it serves anything), and the Router is built once at
startup.
"""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import asynccontextmanager
from http import HTTPStatus
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials

from .auth import bearer_scheme, verify_bearer_token
from .completion_service import CompletionService
from .config import Config
from .exceptions import InferenceCallAPIError, SearchEngineError
from .models import (
    CompletionRequest,
    CompletionResponse,
    Health,
    Problem,
    SearchRequest,
    SearchResponse,
)
from .search_service import SearchServiceClient


config = Config.from_env()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # One Router for the process, as the core's `@cache`d `_default_router`.
    app.state.completions = CompletionService(config.system.llm.create_router())
    app.state.search = SearchServiceClient(config.system.web_search)
    yield


app = FastAPI(
    title="Kumoss LLM Service",
    version="1.0.2",  # x-release-please-version
    description="Reference implementation of contracts/openapi/llm.v1.yaml.",
    lifespan=lifespan,
)


def _problem(
    status_code: int,
    title: str,
    detail: str | None = None,
    headers: Mapping[str, str] | None = None,
    **extensions: Any,
) -> JSONResponse:
    payload = Problem(
        type="about:blank", title=title, status=status_code, detail=detail, **extensions
    ).model_dump(exclude_none=True)
    return JSONResponse(
        status_code=status_code,
        content=payload,
        media_type="application/problem+json",
        headers=headers,
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(_request: Request, exc: HTTPException) -> JSONResponse:
    return _problem(exc.status_code, exc.detail or "HTTP error", headers=exc.headers)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    _request: Request, exc: RequestValidationError
) -> JSONResponse:
    # FastAPI's default 422 handler returns application/json; the contract
    # mandates application/problem+json for every error response.
    return _problem(422, "Request validation failed", str(exc))


@app.exception_handler(InferenceCallAPIError)
async def inference_error_handler(
    _request: Request, exc: InferenceCallAPIError
) -> JSONResponse:
    # Always a 502 on the wire; the provider's own status rides along as
    # `status_code` (the core's `InferenceCallAPIError.error_code`). Built
    # by hand because it may be null, which `exclude_none` would drop.
    return JSONResponse(
        status_code=status.HTTP_502_BAD_GATEWAY,
        content={
            "type": "about:blank",
            "title": "Inference call failed",
            "status": status.HTTP_502_BAD_GATEWAY,
            "detail": exc.message,
            "status_code": exc.error_code,
        },
        media_type="application/problem+json",
    )


@app.exception_handler(SearchEngineError)
async def search_engine_error_handler(
    _request: Request, exc: SearchEngineError
) -> JSONResponse:
    # 400 (no provider configured) or 502 (the engine call failed); the
    # detail is the core's `SearchEngineError.message`, verbatim.
    return _problem(exc.error_code, HTTPStatus(exc.error_code).phrase, exc.message)


@app.exception_handler(Exception)
async def unhandled_exception_handler(
    _request: Request, exc: Exception
) -> JSONResponse:
    return _problem(500, "Internal server error", str(exc))


async def require_bearer_token(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> None:
    """Reject the request unless it carries the configured bearer token."""
    verify_bearer_token(config, credentials)


Authenticated = Depends(require_bearer_token)


@app.get("/v1/healthz", response_model=Health, tags=["ops"])
async def healthz() -> Health:
    return Health(status="ok")


# Unversioned alias: every other bundled service (and its compose
# healthcheck) probes `/healthz`.
app.add_api_route(
    "/healthz",
    healthz,
    methods=["GET"],
    response_model=Health,
    tags=["ops"],
    include_in_schema=False,
)


@app.post(
    "/v1/completions",
    response_model=CompletionResponse,
    tags=["completions"],
    dependencies=[Authenticated],
)
async def completions(request: Request, body: CompletionRequest) -> CompletionResponse:
    # Only the keys the caller sent: an omitted (or null) optional stays
    # omitted, so LiteLLM sees exactly the kwargs the core's adapter used
    # to build. Filtered at the top level only — `exclude_none` would also
    # strip nulls inside `messages` (e.g. an assistant tool-call turn's
    # `"content": null`).
    kwargs = {
        key: value
        for key, value in body.model_dump().items()
        if value is not None or key not in _OPTIONAL_COMPLETION_KEYS
    }
    return await request.app.state.completions.complete(kwargs)


_OPTIONAL_COMPLETION_KEYS = frozenset({"tools", "tool_choice", "reasoning_effort"})


@app.post(
    "/v1/search",
    response_model=SearchResponse,
    tags=["search"],
    dependencies=[Authenticated],
)
async def search(request: Request, body: SearchRequest) -> SearchResponse:
    results = await request.app.state.search.search(body.query)
    return SearchResponse(results=results)
