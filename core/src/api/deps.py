# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""FastAPI dependencies for authentication and role-based authorization."""

from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.domains.entities import User
from src.domains.services.database_service import DatabaseService
from src.domains.services.user_service import UserService
from src.infrastructure.auth import oidc
from src.infrastructure.exceptions import TokenValidationError
from src.shared.config.system_config import system_config
from src.shared.constants import OperationRole, PanelRole
from src.shared.exceptions import ExceptionHandler


_bearer = HTTPBearer(auto_error=False)


def _oidc_enabled() -> bool:
    return bool(system_config.oidc.issuer_url)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    if not _oidc_enabled():
        return await UserService.resolve()
    if credentials is None or oidc.oidc_validator is None:
        raise HTTPException(
            status_code=401,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        claims = await oidc.oidc_validator.validate(credentials.credentials)
    except TokenValidationError as e:
        raise HTTPException(
            status_code=401,
            detail=e.message,
            headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
        )
    return await UserService.resolve(claims)


def require_operation_role(minimum: OperationRole):
    async def dependency(
        user: Annotated[User, Depends(get_current_user)],
    ) -> User:
        if not user.operation_role.at_least(minimum):
            raise HTTPException(
                status_code=403,
                detail=f"Requires operation role '{minimum.value}' or higher",
            )
        return user

    return dependency


def require_panel_role(minimum: PanelRole):
    async def dependency(
        user: Annotated[User, Depends(get_current_user)],
    ) -> User:
        if user.panel_role is None or not user.panel_role.at_least(minimum):
            raise HTTPException(
                status_code=403,
                detail=f"Requires admin-panel role '{minimum.value}' or higher",
            )
        return user

    return dependency


async def assert_session_access(user: User, session_id: UUID, *, write: bool) -> None:
    """Owner may always access; non-owners may read with panel viewer+."""
    try:
        owner_pk = await DatabaseService.get_session_owner(session_id)
    except ExceptionHandler as e:
        raise HTTPException(status_code=e.error_code, detail=e.message)
    if owner_pk == user.id:
        return
    if not write and user.panel_role is not None:
        return
    raise HTTPException(status_code=403, detail="Not the session owner")
