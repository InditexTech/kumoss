# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Passthrough for the mapping microservice contract.

Forwards requests from the browser-facing api to the mapping service
defined in `contracts/openapi/mapping.v1.yaml`. When mapping is
disabled in system config, the underlying client returns identity
passthrough so the OSS-default deploy keeps working without a
configured mapper.
"""

from typing import Annotated

from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse

from src.infrastructure.external.mapping_service import MappingServiceClient

router = APIRouter(prefix="/mapping", tags=["Mapping"])


@router.post(
    path="/resolve",
    summary="Resolve a business identifier into an IaC repository reference.",
    responses={
        200: {
            "description": "Identifier resolved (or identity-passed when disabled).",
            "content": {
                "application/json": {
                    "example": {
                        "repo_url": "https://github.com/me/my-iac.git",
                        "project": "my-iac",
                        "branch": None,
                        "path": None,
                    }
                }
            },
        },
    },
)
async def resolve(
    identifier: Annotated[str, Body(description="Business identifier to resolve.")],
    cloud: Annotated[
        str | None,
        Body(description="Optional cloud hint (azure, gcp, aws, ...)."),
    ] = None,
    environment: Annotated[
        str | None,
        Body(
            description="Optional deployment-dimension hint (dev, staging, pro, ...)."
        ),
    ] = None,
):
    resolved = await MappingServiceClient().resolve(
        identifier,
        cloud=cloud,
        environment=environment,
    )
    return JSONResponse(
        content={
            "repo_url": resolved.repo_url,
            "project": resolved.project,
            "branch": resolved.branch,
            "path": resolved.path,
        }
    )
