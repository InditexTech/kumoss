# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Read and cancel the queued terraform operations of the caller's sessions."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from src.api.deps import assert_session_access, get_current_user
from src.api.dtos import OperationResponse, PaginatedOperations
from src.domains.entities import User
from src.domains.services.operation_queue_service import OperationQueueService
from src.domains.services.operation_schedule_service import OperationScheduleService
from src.infrastructure.database.models import Operation
from src.shared.config.system_config import system_config
from src.shared.constants import OperationStatus, OperationType
from src.shared.exceptions import ExceptionHandler

router = APIRouter(prefix="/operations", tags=["Operations"])

_queue = OperationQueueService(system_config.scheduler)


def _response(op: Operation) -> OperationResponse:
    return OperationResponse(
        uuid=op.uuid,
        session_uuid=op.session.uuid,
        schedule_uuid=op.schedule.uuid if op.schedule else None,
        kind=op.kind,
        status=op.status,
        params=op.params,
        scheduled_at=op.scheduled_at,
        started_at=op.started_at,
        finished_at=op.finished_at,
        error=op.error,
        created_at=op.created_at,
    )


async def _load(user: User, operation_id: UUID, *, write: bool) -> Operation:
    op = await _queue.get_operation(operation_id)
    if op is None:
        raise HTTPException(status_code=404, detail="Operation not found")
    await assert_session_access(user, op.session.uuid, write=write)
    return op


@router.get(path="", summary="List the operations of the caller's sessions.")
async def list_operations(
    user: Annotated[User, Depends(get_current_user)],
    session_id: Annotated[UUID | None, Query()] = None,
    schedule_uuid: Annotated[UUID | None, Query()] = None,
    kind: Annotated[OperationType | None, Query()] = None,
    status: Annotated[OperationStatus | None, Query()] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> PaginatedOperations:
    schedule_pk = None
    if schedule_uuid is not None:
        schedule = await OperationScheduleService.get(schedule_uuid)
        if schedule is None or schedule.user_id != user.id:
            return PaginatedOperations(
                items=[], total=0, page=page, page_size=page_size
            )
        schedule_pk = schedule.id
    items, total = await _queue.list_operations(
        user_pk=user.id,
        session_id=session_id,
        schedule_pk=schedule_pk,
        kind=kind,
        status=status,
        offset=(page - 1) * page_size,
        limit=page_size,
    )
    return PaginatedOperations(
        items=[_response(op) for op in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    path="/{operation_id}",
    summary="Get operation detail.",
    responses={404: {"description": "Operation not found."}},
)
async def get_operation(
    operation_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
) -> OperationResponse:
    return _response(await _load(user, operation_id, write=False))


@router.post(
    path="/{operation_id}/cancel",
    summary="Cancel a pending or running operation.",
    status_code=202,
    responses={
        404: {"description": "Operation not found."},
        409: {"description": "Operation already finished."},
    },
)
async def cancel_operation(
    operation_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
) -> OperationResponse:
    """Pending operations are cancelled at once; a running one is stopped
    by its worker at the next heartbeat."""
    op = await _load(user, operation_id, write=True)
    try:
        await _queue.cancel(op)
    except ExceptionHandler as e:
        raise HTTPException(status_code=e.error_code, detail=e.message)
    return _response(await _load(user, operation_id, write=True))
