# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""FastAPI application for the mapping reference implementation.

An ``identifier`` that is an https URL is returned unchanged as the
``repo_url``. A bare repository name is appended to
``MAPPING_PREFIX_IDENTIFIER`` with a ``.git`` suffix, so ``foo`` under
``https://github.com/my-org/`` resolves to
``https://github.com/my-org/foo.git``. Anything else answers 404.
Organizations with a real catalogue substitute their own implementation
against the same contract.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials

from .auth import bearer_scheme, verify_bearer_token
from .config import Config
from .models import Health, Problem, ResolveRequest, ResolveResponse
from .resolver import NotResolvable, resolve as resolve_identifier


config = Config.from_env()


app = FastAPI(
    title="Kumoss Mapping Service",
    version="2.0.0",
    description="Reference implementation of contracts/openapi/mapping.v1.yaml.",
)


def _problem(
    status_code: int,
    title: str,
    detail: str | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    payload = Problem(
        type="about:blank", title=title, status=status_code, detail=detail
    ).model_dump(exclude_none=True)
    return JSONResponse(
        status_code=status_code,
        content=payload,
        media_type="application/problem+json",
        headers=headers,
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    return _problem(exc.status_code, exc.detail or "HTTP error", headers=exc.headers)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    for error in exc.errors():
        if error.get("type") == "json_invalid":
            return _problem(400, "Malformed request body", str(exc))
    return _problem(422, "Request validation failed", str(exc))


@app.exception_handler(NotResolvable)
async def not_resolvable_handler(request: Request, exc: NotResolvable) -> JSONResponse:
    return _problem(404, "Identifier could not be resolved", str(exc))


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    return _problem(500, "Internal server error", str(exc))


async def require_bearer_token(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> None:
    """Reject the request unless it carries the configured bearer token."""
    verify_bearer_token(config, credentials)


Authenticated = Depends(require_bearer_token)


@app.get("/healthz", response_model=Health, tags=["ops"])
async def healthz() -> Health:
    return Health(status="ok")


@app.post(
    "/v1/resolve",
    response_model=ResolveResponse,
    status_code=status.HTTP_200_OK,
    tags=["resolve"],
    dependencies=[Authenticated],
)
async def resolve(body: ResolveRequest) -> ResolveResponse:
    # NotResolvable becomes a 404 problem document in its handler above.
    repo_url = resolve_identifier(body.identifier, config.prefix_identifier)
    return ResolveResponse(repo_url=repo_url, identifier=body.identifier)
