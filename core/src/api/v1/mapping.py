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

from fastapi import APIRouter, Depends, HTTPException

from src.api.deps import get_current_user
from src.api.dtos import MappingResolveRequest, MappingResolveResponse
from src.infrastructure.external.mapping_service import MappingServiceClient
from src.shared.exceptions import ExceptionHandler

router = APIRouter(prefix="/mapping", tags=["Mapping"])


@router.post(
    path="/resolve",
    dependencies=[Depends(get_current_user)],
    response_model=MappingResolveResponse,
    summary="Resolve a business identifier into an IaC repository reference.",
    responses={
        200: {
            "description": "Identifier resolved (or identity-passed when disabled).",
        },
        502: {"description": "The mapping service failed or answered off-contract."},
        504: {"description": "The mapping service timed out."},
    },
)
async def resolve(body: MappingResolveRequest) -> MappingResolveResponse:
    try:
        resolved = await MappingServiceClient().resolve(
            body.identifier,
            terraform_provider=body.terraform_provider,
        )
    except ExceptionHandler as e:
        raise HTTPException(status_code=e.error_code, detail=e.message)
    return MappingResolveResponse(
        repo_url=resolved.repo_url,
        identifier=resolved.identifier,
        terraform_provider=resolved.terraform_provider,
        scope_id=resolved.scope_id,
    )
