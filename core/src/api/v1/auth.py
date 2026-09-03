# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from fastapi import APIRouter

from src.api.dtos import AuthConfigResponse
from src.shared.config.system_config import system_config

# Deliberately unauthenticated: the SPA must read this before it can log in.
router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.get(
    path="/config",
    summary="Public OIDC settings for the SPA login flow.",
)
async def auth_config() -> AuthConfigResponse:
    oidc = system_config.oidc
    return AuthConfigResponse(
        issuer_url=oidc.issuer_url,
        client_id=oidc.client_id,
        audience=oidc.audience,
        scope=oidc.scope,
    )
