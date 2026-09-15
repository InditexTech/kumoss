# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""FastAPI application for the authz reference implementation."""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.security import HTTPAuthorizationCredentials

from . import store
from .auth import bearer_scheme, verify_bearer_token
from .config import Config
from .models import (
    AssignRoleRequest,
    CheckRequest,
    CheckResponse,
    Health,
    Problem,
    Role,
    RoleList,
    User,
    UserList,
)


config = Config.from_env()


@asynccontextmanager
async def lifespan(app: FastAPI):
    if config.root_admin_email:
        store.bootstrap_root_admin(
            Path(config.role_store_path), config.root_admin_email
        )
    yield


app = FastAPI(
    title="Nebula Authorization Service",
    version="1.0.0",
    description="Reference implementation of contracts/openapi/authz.v1.yaml.",
    lifespan=lifespan,
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


def _require_admin(
    credentials: HTTPAuthorizationCredentials | None, user_id: str | None
) -> None:
    verify_bearer_token(config, credentials)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="X-User-Id header required for admin operations.",
        )
    if not store.has_role(Path(config.role_store_path), user_id, "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Caller does not hold the admin role.",
        )


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
    "/v1/check",
    response_model=CheckResponse,
    tags=["check"],
    dependencies=[Authenticated],
)
async def check(body: CheckRequest) -> CheckResponse:
    if config.permissive_check:
        return CheckResponse(
            authorized=True,
            portal_url=None,
            reason=(
                "Permissive OSS reference impl: all checks return true. "
                "Replace this implementation with real authorization "
                "logic (e.g., cloud SPN access check) for production."
            ),
        )

    # When permissive_check is off, the OSS reference impl still has no
    # built-in cloud check — it returns false so misconfigurations are
    # visible rather than silently granting access.
    return CheckResponse(
        authorized=False,
        portal_url=None,
        reason=(
            "Permissive mode disabled and no cloud-check implementation "
            f"is configured for {body.cloud}/{body.project}."
        ),
    )


@app.get(
    "/v1/users/me",
    response_model=User,
    tags=["users"],
    dependencies=[Authenticated],
)
async def get_current_user(
    x_user_id: str | None = Header(default=None),
    x_user_email: str | None = Header(default=None),
) -> User:
    if not x_user_id:
        # Anonymous: no identity asserted by the caller.
        return User(id="anonymous", email=None, name=None, roles=[])

    # Truncate to the model's max length. The contract documents 1024;
    # over-length headers are clamped rather than rejected so flaky
    # callers don't get hard failures from boundary cases.
    user_id = x_user_id[:1024]
    user_email = x_user_email[:256] if x_user_email else None
    record = store.get_or_create_user(Path(config.role_store_path), user_id, user_email)
    return User(**record)


@app.get(
    "/v1/roles",
    response_model=RoleList,
    tags=["roles"],
    dependencies=[Authenticated],
)
async def list_roles() -> RoleList:
    return RoleList(
        roles=[
            Role(name=name, description=desc)
            for name, desc in store.KNOWN_ROLES.items()
        ]
    )


@app.get("/v1/users", response_model=UserList, tags=["users"])
async def list_users(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    x_user_id: str | None = Header(default=None),
) -> UserList:
    _require_admin(credentials, x_user_id)
    users = store.list_users(Path(config.role_store_path))
    return UserList(users=[User(**u) for u in users])


@app.post(
    "/v1/users/{user_id}/roles",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["roles"],
)
async def assign_role(
    user_id: str,
    body: AssignRoleRequest,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    x_user_id: str | None = Header(default=None),
) -> Response:
    _require_admin(credentials, x_user_id)
    try:
        store.assign_role(Path(config.role_store_path), user_id, body.role)
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown role: {body.role}",
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.delete(
    "/v1/users/{user_id}/roles/{role}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["roles"],
)
async def revoke_role(
    user_id: str,
    role: str,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    x_user_id: str | None = Header(default=None),
) -> Response:
    _require_admin(credentials, x_user_id)
    store.revoke_role(Path(config.role_store_path), user_id, role)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
