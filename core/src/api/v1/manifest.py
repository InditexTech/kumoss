# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from fastapi import APIRouter, Depends, HTTPException

from src.api.deps import require_operation_role
from src.api.dtos import ManifestProbeRequest, ManifestProbeResponse
from src.application.factory import ApplicationFactory
from src.shared.constants import OperationRole
from src.shared.exceptions import ExceptionHandler

router = APIRouter(prefix="/manifest", tags=["Manifest"])


@router.post(
    path="/probe",
    dependencies=[Depends(require_operation_role(OperationRole.DEVELOPER))],
    summary="What a root module needs before a session can run on it.",
    description=(
        "Reads the root module on the repository's default branch and compares it "
        "with its committed manifest (`kumoss.yaml`). When `needs_input` is true, the "
        "first session call must carry `manifest` answers for `missing_variables` "
        "(and a var file choice); otherwise the session sets the manifest up on its "
        "own. Never returns variable values."
    ),
    responses={
        400: {
            "description": "Repository unreachable, or root_module_path is not a directory in it."
        },
        422: {
            "description": "The Terraform configuration or its manifest cannot be read."
        },
        502: {"description": "Cloning the repository failed."},
    },
)
async def probe_manifest(request: ManifestProbeRequest) -> ManifestProbeResponse:
    try:
        resolution = await ApplicationFactory.get_manifest_probe_service().probe(
            repo_uri=request.repo_uri,
            root_module_path=request.root_module_path,
        )
    except ExceptionHandler as e:
        raise HTTPException(status_code=e.error_code, detail=e.message)
    return ManifestProbeResponse.from_resolution(resolution)
