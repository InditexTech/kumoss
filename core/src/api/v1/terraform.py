# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from src.api.deps import assert_session_access, require_operation_role
from src.api.dtos import OperationAcceptedResponse
from src.domains.entities import User
from src.domains.services.operation_queue_service import OperationQueueService
from src.application.iac_requests import (
    BaseIacRequest,
    GenerateRequest,
    DriftRequest,
    ApplyRequest,
    ImportRequest,
)
from src.application.services.operation_submission_service import (
    OPERATION_MIN_ROLE,
    IacRequest,
    OperationSubmissionService,
)
from src.infrastructure.filesystem import WorkspaceService
from src.shared.config.system_config import system_config
from src.shared.constants import OperationType
from src.shared.exceptions import ExceptionHandler

router = APIRouter(
    prefix="/iac",
    tags=["Infrastructure as Code"],
    responses={
        400: {
            "description": "Repository URI was rejected (unreachable or not allowed)."
        },
        404: {"description": "Iteration call referenced an unknown session."},
    },
)

_workspace = WorkspaceService()
_submission = OperationSubmissionService(OperationQueueService(system_config.scheduler))


async def _submit(
    request: IacRequest, kind: OperationType, user: User
) -> OperationAcceptedResponse:
    """Validate the call and queue it; the operation workers run it.

    Session-only requests (e.g. apply) carry no ``repo_uri``: URI
    validation applies only to request models that define the field.
    Calls referencing an existing session are owner-only.
    """
    if request.session_id is not None:
        await assert_session_access(user, request.session_id, write=True)
    try:
        if isinstance(request, BaseIacRequest) and request.repo_uri is not None:
            await _workspace.validate_uri(request.repo_uri)
        ctx, op = await _submission.submit(request, kind, user.id)
    except ExceptionHandler as e:
        raise HTTPException(status_code=e.error_code, detail=e.message)
    return OperationAcceptedResponse(session_id=ctx.id, operation_id=op.uuid)


@router.post(
    path="/generate",
    status_code=202,
    summary="Start an IaC generation session.",
    responses={409: {"description": "Session already has an operation in flight."}},
)
async def generate_infrastructure(
    request: GenerateRequest,
    user: Annotated[
        User,
        Depends(require_operation_role(OPERATION_MIN_ROLE[OperationType.GENERATE])),
    ],
) -> OperationAcceptedResponse:
    """Generates, validates, and prepares IaC based on a user query.
    Returns the session and queued operation ids for tracking.
    """
    return await _submit(request, OperationType.GENERATE, user)


@router.post(
    path="/drift",
    status_code=202,
    summary="Start a drift detection and remediation session",
    responses={409: {"description": "Session already has an operation in flight."}},
)
async def drift_detection_remediation(
    request: DriftRequest,
    user: Annotated[
        User, Depends(require_operation_role(OPERATION_MIN_ROLE[OperationType.DRIFT]))
    ],
) -> OperationAcceptedResponse:
    """Performs Terraform drift detection and remediation.
    Returns the session and queued operation ids for tracking.
    """
    return await _submit(request, OperationType.DRIFT, user)


@router.post(
    path="/apply",
    status_code=202,
    summary="Start an apply session for prepared infrastructure changes.",
    responses={
        409: {
            "description": "Session is blocked or already has an operation in flight."
        },
    },
)
async def apply_infrastructure(
    request: ApplyRequest,
    user: Annotated[
        User, Depends(require_operation_role(OPERATION_MIN_ROLE[OperationType.APPLY]))
    ],
) -> OperationAcceptedResponse:
    """Applies the plan pinned by the session's last successful generate or
    drift round — exactly the reviewed changes, with no re-plan at apply time.
    Returns the session and queued operation ids for tracking.
    """
    return await _submit(request, OperationType.APPLY, user)


@router.post(
    path="/import",
    status_code=202,
    summary="Start an IaC import session.",
    responses={409: {"description": "Session already has an operation in flight."}},
)
async def import_infrastructure(
    request: ImportRequest,
    user: Annotated[
        User, Depends(require_operation_role(OPERATION_MIN_ROLE[OperationType.IMPORT]))
    ],
) -> OperationAcceptedResponse:
    """Imports, validates, and prepares IaC based on a user query.
    Returns the session and queued operation ids for tracking.
    """
    return await _submit(request, OperationType.IMPORT, user)
