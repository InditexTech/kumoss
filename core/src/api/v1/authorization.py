# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from typing import Annotated

from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse

from src.infrastructure.external.authz_service import AuthzServiceClient

router = APIRouter(prefix="/authorize", tags=["Authorization"])


@router.post(
    path="/",
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
    user_email: Annotated[
        str, Body(description="user email that is requesting access")
    ],
):
    result = await AuthzServiceClient().check(
        cloud=cloud,
        project=project_name,
        environment=environment,
        user_id=user_email,
    )

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
