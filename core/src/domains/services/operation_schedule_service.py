# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Cron arithmetic for recurring operation schedules; persistence lives in
``DatabaseService``."""

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from croniter import CroniterBadDateError, croniter

from src.domains.services.database_service import DatabaseService
from src.infrastructure.database.models import OperationSchedule
from src.shared.constants import OperationType


class OperationScheduleService:
    @staticmethod
    def is_valid_cron(cron: str) -> bool:
        """Five-field (minute resolution) expressions that can ever fire.

        croniter also accepts 6/7-field crons with a seconds field, which
        would fire on every poll, and impossible dates like ``0 0 31 2 *``
        that only fail once ``get_next`` is asked for a fire time.
        """
        if len(cron.split()) != 5 or not croniter.is_valid(cron):
            return False
        try:
            _ = OperationScheduleService.next_run(cron)
        except CroniterBadDateError:
            return False
        return True

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
        return await DatabaseService.create_schedule(
            user_pk=user_pk,
            name=name,
            kind=kind,
            cron=cron,
            params=params,
            enabled=enabled,
            next_run_at=OperationScheduleService.next_run(cron),
        )

    @staticmethod
    async def get(schedule_id: UUID) -> OperationSchedule | None:
        return await DatabaseService.get_schedule(schedule_id)

    @staticmethod
    async def list_for_user(
        user_pk: int, offset: int, limit: int, kind: OperationType | None = None
    ) -> tuple[list[OperationSchedule], int]:
        return await DatabaseService.list_schedules(user_pk, offset, limit, kind)

    @staticmethod
    async def update(schedule_pk: int, values: dict[str, Any]) -> None:
        await DatabaseService.update_schedule(schedule_pk, values)

    @staticmethod
    async def delete(schedule_pk: int) -> None:
        await DatabaseService.delete_schedule(schedule_pk)

    @staticmethod
    async def list_due(now: datetime) -> list[OperationSchedule]:
        return await DatabaseService.list_due_schedules(now)

    @staticmethod
    async def claim_fire(schedule: OperationSchedule, now: datetime) -> bool:
        """Advance the schedule past ``now``; True only for the one replica
        that wins this fire time (see ``DatabaseService.advance_schedule``)."""
        return await DatabaseService.advance_schedule(
            schedule, OperationScheduleService.next_run(schedule.cron, now), now
        )
