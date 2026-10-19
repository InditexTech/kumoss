# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Recurring (cron) terraform operations owned by the caller.

A fired schedule submits its ``params`` exactly like a first call to the
matching ``/iac`` endpoint, as the schedule's owner.
"""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from src.api.deps import get_current_user
from src.api.dtos import (
    CreateScheduleRequest,
    PaginatedSchedules,
    ScheduleResponse,
    UpdateScheduleRequest,
)
from src.application.services.operation_submission_service import (
    OPERATION_MIN_ROLE,
    schedule_request,
)
from src.domains.entities import User
from src.domains.services.database_service import DatabaseService
from src.domains.services.operation_schedule_service import OperationScheduleService
from src.infrastructure.database.models import OperationSchedule
from src.infrastructure.filesystem import WorkspaceService
from src.shared.constants import OperationType
from src.shared.exceptions import ExceptionHandler

router = APIRouter(prefix="/schedules", tags=["Schedules"])

_workspace = WorkspaceService()


async def _response(schedule: OperationSchedule) -> ScheduleResponse:
    owner = await DatabaseService.get_user(schedule.user_id)
    return ScheduleResponse(
        uuid=schedule.uuid,
        owner_email=owner.email if owner else None,
        name=schedule.name,
        kind=schedule.kind,
        cron=schedule.cron,
        enabled=schedule.enabled,
        params=schedule.params,
        next_run_at=schedule.next_run_at,
        last_run_at=schedule.last_run_at,
        created_at=schedule.created_at,
    )


async def _validated_params(
    user: User, kind: OperationType, params: dict[str, Any]
) -> dict[str, Any]:
    """Role-check the kind and normalize params as its first-call request."""
    if not user.operation_role.at_least(OPERATION_MIN_ROLE[kind]):
        raise HTTPException(
            status_code=403,
            detail=f"Requires operation role '{OPERATION_MIN_ROLE[kind].value}' or higher",
        )
    try:
        request = schedule_request(kind, params)
        if request.repo_uri is not None:
            await _workspace.validate_uri(request.repo_uri)
    except ExceptionHandler as e:
        raise HTTPException(status_code=e.error_code, detail=e.message)
    return request.model_dump(mode="json", exclude_none=True)


async def _load(user: User, schedule_id: UUID, *, write: bool) -> OperationSchedule:
    """Owner may always access; non-owners may read with panel viewer+."""
    schedule = await OperationScheduleService.get(schedule_id)
    if schedule is None:
        raise HTTPException(status_code=404, detail="Schedule not found")
    if schedule.user_id != user.id and (write or user.panel_role is None):
        raise HTTPException(status_code=403, detail="Not the schedule owner")
    return schedule


@router.post(
    path="",
    summary="Create a recurring schedule.",
    status_code=201,
    responses={403: {"description": "Caller lacks the role for this kind."}},
)
async def create_schedule(
    request: CreateScheduleRequest,
    user: Annotated[User, Depends(get_current_user)],
) -> ScheduleResponse:
    params = await _validated_params(user, request.kind, request.params)
    schedule = await OperationScheduleService.create(
        user_pk=user.id,
        name=request.name,
        kind=request.kind,
        cron=request.cron,
        params=params,
        enabled=request.enabled,
    )
    return await _response(schedule)


@router.get(path="", summary="List the caller's schedules.")
async def list_schedules(
    user: Annotated[User, Depends(get_current_user)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> PaginatedSchedules:
    items, total = await OperationScheduleService.list_for_user(
        user.id, offset=(page - 1) * page_size, limit=page_size
    )
    return PaginatedSchedules(
        items=[await _response(s) for s in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    path="/{schedule_id}",
    summary="Get schedule detail.",
    responses={404: {"description": "Schedule not found."}},
)
async def get_schedule(
    schedule_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
) -> ScheduleResponse:
    return await _response(await _load(user, schedule_id, write=False))


@router.patch(
    path="/{schedule_id}",
    summary="Update a schedule.",
    responses={404: {"description": "Schedule not found."}},
)
async def update_schedule(
    schedule_id: UUID,
    request: UpdateScheduleRequest,
    user: Annotated[User, Depends(get_current_user)],
) -> ScheduleResponse:
    schedule = await _load(user, schedule_id, write=True)
    values: dict[str, Any] = request.model_dump(exclude_none=True)
    if request.params is not None:
        values["params"] = await _validated_params(user, schedule.kind, request.params)
    cron = values.get("cron", schedule.cron)
    if "cron" in values or (request.enabled and not schedule.enabled):
        values["next_run_at"] = OperationScheduleService.next_run(cron)
    if values:
        await OperationScheduleService.update(schedule.id, values)
    return await _response(await _load(user, schedule_id, write=True))


@router.delete(
    path="/{schedule_id}",
    summary="Delete a schedule.",
    status_code=204,
    responses={404: {"description": "Schedule not found."}},
)
async def delete_schedule(
    schedule_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
) -> None:
    schedule = await _load(user, schedule_id, write=True)
    await OperationScheduleService.delete(schedule.id)
