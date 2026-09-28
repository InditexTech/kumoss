# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import JSONResponse

from src.api.deps import get_current_user
from src.api.dtos import AuthConfigResponse
from src.domains.entities import User
from src.infrastructure.external.authz_service import AuthzServiceClient
from src.infrastructure.storage import default_object_storage
from src.shared.config.system_config import system_config
from src.shared.exceptions import ExceptionHandler

router = APIRouter(prefix="/auth", tags=["Authentication"])


# Deliberately unauthenticated: the SPA must read this before it can log in.
@router.get(
    path="/config",
    summary="Public settings the SPA needs before it can render.",
)
async def auth_config() -> AuthConfigResponse:
    oidc = system_config.oidc
    return AuthConfigResponse(
        issuer_url=oidc.issuer_url,
        client_id=oidc.client_id,
        audience=oidc.audience,
        scope=oidc.scope,
        artifact_metadata_header_prefix=(
            default_object_storage().metadata_header_prefix
        ),
    )


@router.post(
    path="/authorize",
    summary="Endpoint to manage if a user has permissions on a given project",
    responses={
        200: {
            "description": "Authorization decision computed.",
            "content": {
                "application/json": {
                    "example": {
                        "result": True,
                        "message": "Authorized",
                        "portalUrl": "https://portal.azure.com/...",
                    }
                }
            },
        },
    },
)
async def authorize(
    cloud: Annotated[
        str, Body(description="cloud provider that the project belongs to")
    ],
    project_name: Annotated[
        str, Body(description="name of the project that we are checking")
    ],
    environment: Annotated[str, Body(description="environment that we are checking")],
    user: Annotated[User, Depends(get_current_user)],
):
    try:
        result = await AuthzServiceClient().check(
            cloud=cloud,
            project=project_name,
            environment=environment,
            user_id=user.email or user.subject,
        )
    except ExceptionHandler as e:
        # Enabled but unreachable / timed-out sidecar: surface the client's
        # 502/504 instead of an unhandled 500. Never an allow.
        raise HTTPException(status_code=e.error_code, detail=e.message)

    if result.authorized:
        message = result.reason or f"Authorized on {project_name}"
    else:
        message = result.reason or (
            f"Not authorized on {cloud}/{project_name} ({environment})"
        )

    return JSONResponse(
        content={
            "result": result.authorized,
            "message": message,
            "portalUrl": result.portal_url,
        }
    )
