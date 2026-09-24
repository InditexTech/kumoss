# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""REST endpoints for operations and schedules management."""

from __future__ import annotations

import uuid as _uuid
from datetime import datetime, timezone
from typing import Annotated

from croniter import croniter
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import update, delete

from src.infrastructure.database import db
from src.infrastructure.database.models import Session, User
from src.scheduler.api.dtos import (
    CreateScheduleRequest,
    OperationResponse,
    PaginatedOperations,
    PaginatedSchedules,
    ScheduleResponse,
    UpdateScheduleRequest,
)
from src.scheduler.constants import OperationKind, OperationStatus
from src.scheduler.models import OperationSchedule
from src.scheduler.queue_service import OperationQueueService
from src.shared.config.system_config import system_config
from src.shared.exceptions import ExceptionHandler

_queue = OperationQueueService(system_config.scheduler)

operations_router = APIRouter(
    prefix="/operations",
    tags=["Operations"],
)


@operations_router.get(
    path="",
    summary="List operations with optional filters.",
)
async def list_operations(
    session_id: Annotated[str | None, Query()] = None,
    kind: Annotated[OperationKind | None, Query()] = None,
    status: Annotated[OperationStatus | None, Query()] = None,
    schedule_uuid: Annotated[str | None, Query()] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> PaginatedOperations:
    resolved_session_id = None
    if session_id is not None:
        try:
            session_row = await db.get_by(Session, uuid=_uuid.UUID(session_id))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid session_id UUID")
        if session_row is not None:
            resolved_session_id = session_row.id

    resolved_schedule_id = None
    if schedule_uuid is not None:
        try:
            sched_row = await db.get_by(OperationSchedule, uuid=_uuid.UUID(schedule_uuid))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid schedule_uuid")
        if sched_row is not None:
            resolved_schedule_id = sched_row.id

    items, total = await _queue.list_operations(
        session_id=resolved_session_id,
        kind=kind,
        status=status,
        schedule_id=resolved_schedule_id,
        page=page,
        page_size=page_size,
    )

    session_ids = {op.session_id for op in items}
    schedule_ids = {op.schedule_id for op in items}

    session_map: dict[int, _uuid.UUID] = {}
    for sid in session_ids:
        row = await db.get_by(Session, id=sid)
        if row:
            session_map[sid] = row.uuid

    schedule_map: dict[int, _uuid.UUID] = {}
    for sid in schedule_ids:
        row = await db.get_by(OperationSchedule, id=sid)
        if row:
            schedule_map[sid] = row.uuid

    return PaginatedOperations(
        items=[
            OperationResponse(
                uuid=op.uuid,
                session_uuid=session_map.get(op.session_id),
                schedule_uuid=schedule_map.get(op.schedule_id),
                kind=op.kind,
                status=op.status,
                params=op.params,
                scheduled_at=op.scheduled_at,
                started_at=op.started_at,
                finished_at=op.finished_at,
                attempt=op.attempt,
                max_attempts=op.max_attempts,
                error=op.error,
                created_at=op.created_at,
            )
            for op in items
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


@operations_router.get(
    path="/{operation_id}",
    summary="Get operation detail.",
    responses={404: {"description": "Operation not found."}},
)
async def get_operation(operation_id: _uuid.UUID) -> OperationResponse:
    op = await _queue.get_operation(operation_id)
    if op is None:
        raise HTTPException(status_code=404, detail="Operation not found")

    session_row = await db.get_by(Session, id=op.session_id)
    schedule_row = await db.get_by(OperationSchedule, id=op.schedule_id)

    return OperationResponse(
        uuid=op.uuid,
        session_uuid=session_row.uuid,
        schedule_uuid=schedule_row.uuid,
        kind=op.kind,
        status=op.status,
        params=op.params,
        scheduled_at=op.scheduled_at,
        started_at=op.started_at,
        finished_at=op.finished_at,
        attempt=op.attempt,
        max_attempts=op.max_attempts,
        error=op.error,
        created_at=op.created_at,
    )


@operations_router.post(
    path="/{operation_id}/cancel",
    summary="Cancel an operation.",
    status_code=200,
    responses={
        404: {"description": "Operation not found."},
        409: {"description": "Operation is already terminal."},
    },
)
async def cancel_operation(operation_id: _uuid.UUID) -> dict[str, str]:
    try:
        await _queue.cancel(operation_id)
    except ExceptionHandler as e:
        raise HTTPException(status_code=e.error_code, detail=e.message)
    return {"status": "cancelled"}

schedules_router = APIRouter(
    prefix="/schedules",
    tags=["Schedules"],
)


@schedules_router.post(
    path="",
    summary="Create a recurring schedule.",
    status_code=201,
    responses={400: {"description": "Invalid cron expression."}},
)
async def create_schedule(request: CreateScheduleRequest) -> ScheduleResponse:
    if not croniter.is_valid(request.cron):
        raise HTTPException(status_code=400, detail="Invalid cron expression")

    now = datetime.now(timezone.utc)
    next_run = croniter(request.cron, now).get_next(datetime)

    user_row = await db.get_by(User, subject=request.user_id)
    if user_row is None:
        raise HTTPException(status_code=404, detail="User not found")

    schedule = await db.create(
        OperationSchedule,
        uuid=_uuid.uuid4(),
        user_id=user_row.id,
        name=request.name,
        kind=request.kind,
        cron=request.cron,
        params=request.params,
        enabled=request.enabled,
        next_run_at=next_run,
    )

    return ScheduleResponse(
        uuid=schedule.uuid,
        user_id=request.user_id,
        name=schedule.name,
        kind=schedule.kind,
        cron=schedule.cron,
        enabled=schedule.enabled,
        params=schedule.params,
        next_run_at=schedule.next_run_at,
        last_run_at=schedule.last_run_at,
        created_at=schedule.created_at,
    )


@schedules_router.get(
    path="",
    summary="List schedules.",
)
async def list_schedules(
    username: Annotated[str | None, Query()] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> PaginatedSchedules:
    filters: dict = {}
    if username is not None:
        user_row = await db.get_by(User, subject=username)
        if user_row is not None:
            filters["user_id"] = user_row.id

    offset = (page - 1) * page_size
    items, total = await db.query(
        OperationSchedule,
        order_by="created_at",
        order_desc=True,
        offset=offset,
        limit=page_size,
        **filters,
    )

    user_ids = {sched.user_id for sched in items}
    user_map: dict[int, str] = {}
    for uid in user_ids:
        row = await db.get_by(User, id=uid)
        if row:
            user_map[uid] = row.subject

    return PaginatedSchedules(
        items=[
            ScheduleResponse(
                uuid=sched.uuid,
                user_id=user_map.get(sched.user_id),
                name=sched.name,
                kind=sched.kind,
                cron=sched.cron,
                enabled=sched.enabled,
                params=sched.params,
                next_run_at=sched.next_run_at,
                last_run_at=sched.last_run_at,
                created_at=sched.created_at,
            )
            for sched in items
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


@schedules_router.get(
    path="/{schedule_id}",
    summary="Get schedule detail.",
    responses={404: {"description": "Schedule not found."}},
)
async def get_schedule(schedule_id: _uuid.UUID) -> ScheduleResponse:
    sched = await db.get_by(OperationSchedule, uuid=schedule_id)
    if sched is None:
        raise HTTPException(status_code=404, detail="Schedule not found")

    user_row = await db.get_by(User, id=sched.user_id)

    return ScheduleResponse(
        uuid=sched.uuid,
        user_id=user_row.subject if user_row else None,
        name=sched.name,
        kind=sched.kind,
        cron=sched.cron,
        enabled=sched.enabled,
        params=sched.params,
        next_run_at=sched.next_run_at,
        last_run_at=sched.last_run_at,
        created_at=sched.created_at,
    )


@schedules_router.patch(
    path="/{schedule_id}",
    summary="Update a schedule.",
    responses={
        400: {"description": "Invalid cron expression."},
        404: {"description": "Schedule not found."},
    },
)
async def update_schedule(
    schedule_id: _uuid.UUID, request: UpdateScheduleRequest
) -> ScheduleResponse:
    sched = await db.get_by(OperationSchedule, uuid=schedule_id)
    if sched is None:
        raise HTTPException(status_code=404, detail="Schedule not found")

    values = {}
    recompute_next_run = False

    if request.name is not None:
        values["name"] = request.name
    if request.params is not None:
        values["params"] = request.params
    if request.cron is not None:
        if not croniter.is_valid(request.cron):
            raise HTTPException(status_code=400, detail="Invalid cron expression")
        values["cron"] = request.cron
        recompute_next_run = True
    if request.enabled is not None:
        values["enabled"] = request.enabled
        if request.enabled and not sched.enabled:
            recompute_next_run = True

    if recompute_next_run:
        cron_expr = values.get("cron", sched.cron)
        now = datetime.now(timezone.utc)
        values["next_run_at"] = croniter(cron_expr, now).get_next(datetime)

    if values:
        async with db.transaction() as session:
            stmt = (
                update(OperationSchedule)
                .where(OperationSchedule.id == sched.id)
                .values(**values)
            )
            await session.execute(stmt)

    updated = await db.get_by(OperationSchedule, uuid=schedule_id)
    user_row = await db.get_by(User, id=updated.user_id)

    return ScheduleResponse(
        uuid=updated.uuid,
        user_id=user_row.subject if user_row else None,
        name=updated.name,
        kind=updated.kind,
        cron=updated.cron,
        enabled=updated.enabled,
        params=updated.params,
        next_run_at=updated.next_run_at,
        last_run_at=updated.last_run_at,
        created_at=updated.created_at,
    )


@schedules_router.delete(
    path="/{schedule_id}",
    summary="Delete a schedule.",
    status_code=204,
    responses={404: {"description": "Schedule not found."}},
)
async def delete_schedule(schedule_id: _uuid.UUID) -> None:
    sched = await db.get_by(OperationSchedule, uuid=schedule_id)
    if sched is None:
        raise HTTPException(status_code=404, detail="Schedule not found")

    async with db.transaction() as session:
        stmt = delete(OperationSchedule).where(OperationSchedule.id == sched.id)
        await session.execute(stmt)
