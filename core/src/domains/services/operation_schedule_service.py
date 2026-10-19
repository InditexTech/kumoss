# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Persistence and cron arithmetic for recurring operation schedules."""

from datetime import datetime, timezone
from typing import Any, cast
from uuid import UUID, uuid4

from croniter import croniter
from sqlalchemy import CursorResult, delete, select, update

from src.infrastructure.database import db
from src.infrastructure.database.models import OperationSchedule
from src.shared.constants import OperationType


class OperationScheduleService:
    @staticmethod
    def is_valid_cron(cron: str) -> bool:
        return croniter.is_valid(cron)

    @staticmethod
    def next_run(cron: str, after: datetime | None = None) -> datetime:
        return croniter(cron, after or datetime.now(timezone.utc)).get_next(datetime)

    @staticmethod
    async def create(
        user_pk: int,
        name: str,
        kind: OperationType,
        cron: str,
        params: dict[str, Any],
        enabled: bool,
    ) -> OperationSchedule:
        return await db.create(
            OperationSchedule,
            uuid=uuid4(),
            user_id=user_pk,
            name=name,
            kind=kind,
            cron=cron,
            params=params,
            enabled=enabled,
            next_run_at=OperationScheduleService.next_run(cron),
        )

    @staticmethod
    async def get(schedule_id: UUID) -> OperationSchedule | None:
        return await db.get_by(OperationSchedule, uuid=schedule_id)

    @staticmethod
    async def list_for_user(
        user_pk: int, offset: int, limit: int
    ) -> tuple[list[OperationSchedule], int]:
        return await db.query(
            OperationSchedule,
            order_by="created_at",
            order_desc=True,
            offset=offset,
            limit=limit,
            user_id=user_pk,
        )

    @staticmethod
    async def update(schedule_pk: int, values: dict[str, Any]) -> None:
        async with db.transaction() as session:
            _ = await session.execute(
                update(OperationSchedule)
                .where(OperationSchedule.id == schedule_pk)
                .values(**values)
            )

    @staticmethod
    async def delete(schedule_pk: int) -> None:
        async with db.transaction() as session:
            _ = await session.execute(
                delete(OperationSchedule).where(OperationSchedule.id == schedule_pk)
            )

    @staticmethod
    async def list_due(now: datetime) -> list[OperationSchedule]:
        async with db.session() as session:
            result = await session.execute(
                select(OperationSchedule).where(
                    OperationSchedule.enabled.is_(True),
                    OperationSchedule.next_run_at <= now,
                )
            )
            return list(result.scalars().all())

    @staticmethod
    async def claim_fire(schedule: OperationSchedule, now: datetime) -> bool:
        """Advance ``next_run_at`` with a CAS; True only for the one winner.

        Guarding on the previously read ``next_run_at`` makes each fire time
        materialize exactly once, even across replicas.
        """
        async with db.transaction() as session:
            res = await session.execute(
                update(OperationSchedule)
                .where(
                    OperationSchedule.id == schedule.id,
                    OperationSchedule.next_run_at == schedule.next_run_at,
                )
                .values(
                    next_run_at=OperationScheduleService.next_run(schedule.cron, now),
                    last_run_at=now,
                )
            )
        return cast(CursorResult[Any], res).rowcount == 1
