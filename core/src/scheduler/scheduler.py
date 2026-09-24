# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import asyncio
import uuid as _uuid
from datetime import datetime, timezone

from croniter import croniter

from src.domains.services.database_service import DatabaseService
from src.infrastructure.database import db
from src.scheduler.config import SchedulerConfig
from src.scheduler.constants import OperationKind
from src.scheduler.executor import OperationExecutor
from src.scheduler.models import OperationSchedule
from src.scheduler.queue_service import OperationQueueService
from src.shared.constants import OperationType, TerraformProvider
from src.infrastructure.database.models import User
from src.shared.logger import logging

from sqlalchemy import select, update


_KIND_TO_OPERATION_TYPE: dict[OperationKind, OperationType] = {
    OperationKind.DRIFT: OperationType.DRIFT,
}


class OperationScheduler:
    """Orchestrates claim loops, the reaper, and the cron materializer."""

    def __init__(
        self,
        queue: OperationQueueService,
        executor: OperationExecutor,
        config: SchedulerConfig,
    ) -> None:
        self._queue = queue
        self._executor = executor
        self._config = config
        self._running = False
        self._tasks: list[asyncio.Task[None]] = []
        self._worker_id = f"worker-{_uuid.uuid4().hex[:12]}"

    async def start(self) -> None:
        self._running = True

        for slot in range(self._config.concurrency):
            task = asyncio.create_task(
                self._claim_loop(slot), name=f"scheduler-claim-{slot}"
            )
            self._tasks.append(task)

        self._tasks.append(
            asyncio.create_task(self._reaper_loop(), name="scheduler-reaper")
        )
        self._tasks.append(
            asyncio.create_task(
                self._cron_materializer_loop(), name="scheduler-cron"
            )
        )

        logging.info(
            f"Scheduler started: {self._config.concurrency} claim workers, "
            f"worker_id={self._worker_id}"
        )

    async def stop(self) -> None:
        self._running = False
        logging.info("Scheduler stopping, waiting for in-flight operations...")

        done, pending = await asyncio.wait(
            self._tasks, timeout=self._config.shutdown_grace_seconds
        )

        for task in pending:
            task.cancel()

        await asyncio.gather(*pending, return_exceptions=True)

        self._tasks.clear()
        logging.info("Scheduler stopped")

    async def _claim_loop(self, slot: int) -> None:
        while self._running:
            try:
                op = await self._queue.claim(self._worker_id)
                if op is not None:
                    await self._executor.execute(op, self._worker_id)
                else:
                    await asyncio.sleep(self._config.claim_interval)
            except asyncio.CancelledError:
                raise
            except Exception:
                logging.exception(f"Claim loop slot {slot} error")
                await asyncio.sleep(self._config.claim_interval)

    async def _reaper_loop(self) -> None:
        while self._running:
            try:
                count = await self._queue.reap_expired_leases()
                if count > 0:
                    logging.info(f"Reaper: reaped {count} expired operation(s)")
            except asyncio.CancelledError:
                raise
            except Exception:
                logging.exception("Reaper loop error")
            await asyncio.sleep(self._config.reaper_interval)

    async def _cron_materializer_loop(self) -> None:
        while self._running:
            try:
                await self._materialize_due_schedules()
            except asyncio.CancelledError:
                raise
            except Exception:
                logging.exception("Cron materializer error")
            await asyncio.sleep(self._config.schedule_poll_interval)

    async def _materialize_due_schedules(self) -> None:
        now = datetime.now(timezone.utc)

        async with db.session() as session:
            stmt = (
                select(OperationSchedule)
                .where(
                    OperationSchedule.enabled.is_(True),
                    OperationSchedule.next_run_at <= now,
                )
            )
            result = await session.execute(stmt)
            schedules = list(result.scalars().all())

        for sched in schedules:
            try:
                await self._materialize_one(sched, now)
            except Exception:
                logging.exception(
                    f"Failed to materialize schedule {sched.uuid}"
                )

    async def _materialize_one(
        self,
        sched: OperationSchedule,
        now: datetime,
    ) -> None:
        next_run = croniter(sched.cron, now).get_next(datetime)

        async with db.transaction() as tx:
            stmt = (
                update(OperationSchedule)
                .where(
                    OperationSchedule.id == sched.id,
                    OperationSchedule.next_run_at == sched.next_run_at,
                )
                .values(next_run_at=next_run)
            )
            result = await tx.execute(stmt)
            if result.rowcount == 0:
                return

        params = sched.params
        fire_time = sched.next_run_at.isoformat()

        operation_type = _KIND_TO_OPERATION_TYPE[sched.kind]

        terraform_prv_str = params.get("terraform_providers", "")
        try:
            terraform_prv = TerraformProvider(terraform_prv_str)
        except ValueError:
            logging.error(
                f"Schedule {sched.uuid}: invalid terraform_provider "
                f"'{terraform_prv_str}'"
            )
            return

        user_row = await db.get_by(User, id=sched.user_id)
        if user_row is None:
            logging.error(f"Schedule {sched.uuid}: user_id {sched.user_id} not found")
            return

        session_uuid = _uuid.uuid4()
        branch_name = f"Nebula/{now.strftime('%Y-%m-%d_%H%M%S')}"

        await DatabaseService.create_session(
            session_id=session_uuid,
            user_pk=sched.user_id,
            operation=operation_type,
            repo_uri=params["repo_uri"],
            terraform_prv=terraform_prv,
            scope_id=params.get("scope_id", ""),
            branch_name=branch_name,
            query=params["q"],
            iac_path=params.get("iac_path", "."),
        )

        op = await self._queue.enqueue(
            session_uuid=session_uuid,
            kind=sched.kind,
            params=params,
            dedup_key=f"sched:{sched.id}:{fire_time}",
            schedule_id=sched.id,
        )

        async with db.transaction() as tx:
            stmt = (
                update(OperationSchedule)
                .where(OperationSchedule.id == sched.id)
                .values(
                    last_run_at=now,
                    last_operation_id=op.id,
                )
            )
            await tx.execute(stmt)

        logging.info(
            f"Materialized schedule {sched.uuid} ({sched.name}): "
            f"session {session_uuid}, operation {op.uuid}, "
            f"next_run_at {next_run.isoformat()}"
        )
