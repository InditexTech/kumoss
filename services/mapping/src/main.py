# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""FastAPI application for the mapping reference implementation.

Identity passthrough: an ``identifier`` that is an https URL is returned
unchanged as the ``repo_url``, ``terraform_provider`` echoes whatever
the caller sent, and ``scope_id`` is always ``null``. Any other
identifier cannot be resolved and answers 404. This is enough for OSS
users who clone real repo URLs directly; production deployments
substitute their own implementation against the same contract.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials

from .auth import bearer_scheme, verify_bearer_token
from .config import Config
from .models import Health, Problem, ResolveRequest, ResolveResponse


config = Config.from_env()


app = FastAPI(
    title="Nebula Mapping Service",
    version="1.0.0",
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
    return _problem(422, "Request validation failed", str(exc))


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    return _problem(500, "Internal server error", str(exc))


async def require_bearer_token(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> None:
    """Reject the request unless it carries the configured bearer token."""
    verify_bearer_token(config, credentials)


Authenticated = Depends(require_bearer_token)


def _is_https_url(uri: str) -> bool:
    try:
        parsed = urlparse(uri.strip())
        return parsed.scheme.lower() == "https" and bool(parsed.hostname)
    except ValueError:
        return False


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
    if not _is_https_url(body.identifier):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Identifier is not an https:// repository URL",
        )
    # Identity passthrough: the identifier IS the repo URL, and nothing
    # is guessed. Sniffing `azure` out of a `dev.azure.com` URL would
    # conflate "hosted on Azure DevOps" with "deploys to Azure", and the
    # caller skips its prompt for every non-null field — so a wrong
    # guess is never shown to the user and never corrected.
    return ResolveResponse(
        repo_url=body.identifier,
        identifier=body.identifier,
        terraform_provider=body.terraform_provider,
        scope_id=None,
    )
