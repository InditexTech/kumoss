# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Background loops of the operation queue: workers, reaper and cron."""

import asyncio
from typing import final
import contextlib
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from uuid import uuid4

from src.application.services.operation_executor import OperationExecutor
from src.application.services.operation_submission_service import (
    OperationSubmissionService,
)
from src.domains.services.database_service import DatabaseService
from src.domains.services.operation_queue_service import OperationQueueService
from src.domains.services.operation_schedule_service import OperationScheduleService
from src.infrastructure.database.models import OperationSchedule
from src.shared.config.system_config import SchedulerConfig
from src.shared.logger import logging


@final
class OperationScheduler:
    """Runs ``concurrency`` claim→execute workers, the lease reaper and the
    cron materializer for the lifetime of the app."""

    def __init__(
        self,
        queue: OperationQueueService,
        executor: OperationExecutor,
        submission: OperationSubmissionService,
        config: SchedulerConfig,
    ) -> None:
        self._queue = queue
        self._executor = executor
        self._submission = submission
        self._config = config
        self._stopping = asyncio.Event()
        self._workers: list[asyncio.Task[None]] = []
        self._background: list[asyncio.Task[None]] = []
        self._worker_id = f"worker-{uuid4().hex[:12]}"
        # Slots of this replica running (or claiming) a cron-fired operation.
        # Counted in-process: reserving before the claim await keeps two
        # slots from both taking the last scheduled slot.
        self._scheduled_running = 0
        self._scheduled_cap = max(
            1, config.concurrency - config.interactive_reserved_slots
        )

    async def start(self) -> None:
        self._stopping.clear()
        self._workers = [
            asyncio.create_task(
                self._claim_loop(slot), name=f"operations-worker-{slot}"
            )
            for slot in range(self._config.concurrency)
        ]
        self._background = [
            asyncio.create_task(
                self._every(self._config.reaper_interval, self._reap),
                name="operations-reaper",
            ),
            asyncio.create_task(
                self._every(
                    self._config.schedule_poll_interval, self._fire_due_schedules
                ),
                name="operations-cron",
            ),
        ]
        logging.info(
            f"Operation workers started: {self._config.concurrency} slots, "
            + f"worker_id={self._worker_id}"
        )

    async def stop(self) -> None:
        """Stop claiming, give running operations the grace period, then interrupt."""
        self._stopping.set()
        for task in self._background:
            _ = task.cancel()
        if self._workers:
            _, pending = await asyncio.wait(
                self._workers, timeout=self._config.shutdown_grace_seconds
            )
            for task in pending:
                _ = task.cancel()
        _ = await asyncio.gather(
            *self._workers, *self._background, return_exceptions=True
        )
        self._workers.clear()
        self._background.clear()
        logging.info("Operation workers stopped")

    async def _sleep(self, seconds: float) -> None:
        with contextlib.suppress(TimeoutError):
            _ = await asyncio.wait_for(self._stopping.wait(), seconds)

    async def _claim_loop(self, slot: int) -> None:
        while not self._stopping.is_set():
            reserved = self._scheduled_running < self._scheduled_cap
            if reserved:
                self._scheduled_running += 1
            try:
                op = await self._queue.claim(self._worker_id, allow_scheduled=reserved)
                if reserved and (op is None or op.schedule_id is None):
                    reserved = False
                    self._scheduled_running -= 1
                if op is None:
                    await self._sleep(self._config.claim_interval)
                    continue
                await self._executor.execute(op, self._worker_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                logging.exception(f"Operation worker {slot} error")
                await self._sleep(self._config.claim_interval)
            finally:
                if reserved:
                    self._scheduled_running -= 1

    async def _every(self, seconds: float, job: Callable[[], Awaitable[None]]) -> None:
        while not self._stopping.is_set():
            try:
                await job()
            except asyncio.CancelledError:
                raise
            except Exception:
                logging.exception(f"{job.__name__} failed")
            await self._sleep(seconds)

    async def _reap(self) -> None:
        count = await self._queue.reap_expired_leases()
        if count > 0:
            logging.info(f"Reaper: failed {count} operation(s) with expired leases")

    async def _fire_due_schedules(self) -> None:
        now = datetime.now(timezone.utc)
        for schedule in await OperationScheduleService.list_due(now):
            try:
                await self._fire(schedule, now)
            except Exception:
                logging.exception(f"Failed to fire schedule {schedule.uuid}")

    async def _fire(self, schedule: OperationSchedule, now: datetime) -> None:
        if not await OperationScheduleService.claim_fire(schedule, now):
            return  # another replica already fired this tick
        if await self._queue.has_active_for_schedule(schedule.id):
            # Never stack runs: a slow run skips the fires it overlaps.
            logging.warning(
                f"Schedule {schedule.uuid} skipped: its previous operation "
                + "is still pending or running"
            )
            return
        user = await DatabaseService.get_user(schedule.user_id)
        if user is None or not user.operation_role.at_least(
            OperationSubmissionService.MIN_ROLE[schedule.kind]
        ):
            logging.warning(
                f"Schedule {schedule.uuid} skipped: owner lacks the role for "
                + f"{schedule.kind.value}"
            )
            return
        request = OperationSubmissionService.schedule_request(
            schedule.kind, schedule.params
        )
        ctx, op = await self._submission.submit(
            request, schedule.kind, user.id, schedule_id=schedule.id
        )
        logging.info(
            f"Fired schedule {schedule.uuid} ({schedule.name}): "
            + f"session {ctx.id}, operation {op.uuid}"
        )
