# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Cron schedules fire through the shared submission path (real Postgres)."""

import asyncio
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

from sqlalchemy import update

from src.application.services.operation_scheduler import OperationScheduler
from src.application.services.operation_submission_service import (
    OperationSubmissionService,
    schedule_request,
)
from src.domains.services.database_service import DatabaseService
from src.domains.services.operation_queue_service import OperationQueueService
from src.domains.services.operation_schedule_service import OperationScheduleService
from src.domains.services.user_service import UserService
from src.infrastructure.database import db
from src.infrastructure.database.models import Base, Operation, OperationSchedule
from src.infrastructure.redis import redis_client
from src.shared.config.system_config import SchedulerConfig
from src.shared.constants import (
    OperationRole,
    OperationStatus,
    OperationType,
    TerraformProvider,
)
from src.shared.exceptions import ExceptionHandler

_PARAMS = {
    "repo_uri": "https://github.example.com/org/iac.git",
    "terraform_providers": "azure",
    "scope_id": "sub-1",
    "iac_path": "infra",
    "q": "detect drift",
}


class TestScheduleRequest(unittest.TestCase):
    def test_valid_params_normalize_to_the_first_call_request(self):
        request = schedule_request(OperationType.DRIFT, _PARAMS)
        self.assertEqual(request.terraform_providers, TerraformProvider.AZURE)
        self.assertFalse(request.is_partial)

    def test_rejections(self):
        cases = {
            "generate is not schedulable": (OperationType.GENERATE, _PARAMS),
            "apply is not schedulable": (OperationType.APPLY, {}),
            "missing q": (
                OperationType.DRIFT,
                {k: v for k, v in _PARAMS.items() if k != "q"},
            ),
            "session iteration": (
                OperationType.IMPORT,
                {"session_id": "917d0485-a0a2-4c34-8f33-a89d28aba9b0", "q": "x"},
            ),
        }
        for name, (kind, params) in cases.items():
            with self.subTest(name), self.assertRaises(ExceptionHandler) as cm:
                _ = schedule_request(kind, params)
            self.assertEqual(cm.exception.error_code, 422)


class TestCronFiring(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await db.initialize()
        await redis_client.initialize()
        async with db.session_manager.engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        self.user = await UserService.resolve()  # elevated: devops
        config = SchedulerConfig(shutdown_grace_seconds=1.0)
        queue = OperationQueueService(config)
        self.scheduler = OperationScheduler(
            queue=queue,
            executor=AsyncMock(),
            submission=OperationSubmissionService(queue),
            config=config,
        )

    async def asyncTearDown(self):
        await redis_client.close()
        await db.close()

    async def _due_schedule(self) -> OperationSchedule:
        schedule = await OperationScheduleService.create(
            user_pk=self.user.id,
            name="nightly drift",
            kind=OperationType.DRIFT,
            cron="0 3 * * *",
            params=_PARAMS,
            enabled=True,
        )
        async with db.transaction() as s:
            _ = await s.execute(
                update(OperationSchedule)
                .where(OperationSchedule.id == schedule.id)
                .values(next_run_at=datetime.now(timezone.utc) - timedelta(minutes=1))
            )
        return schedule

    async def test_a_due_schedule_queues_an_operation_on_a_fresh_session(self):
        schedule = await self._due_schedule()

        await self.scheduler._fire_due_schedules()

        [op] = await db.list_by(Operation)
        self.assertEqual(op.kind, OperationType.DRIFT)
        self.assertEqual(op.status, OperationStatus.PENDING)
        self.assertEqual(op.schedule_id, schedule.id)
        ctx = await DatabaseService.get_session_context(op.session.uuid)
        self.assertEqual(ctx.repo_uri, _PARAMS["repo_uri"])
        self.assertTrue(ctx.branch_name.startswith("Kumoss/"))
        fired = await OperationScheduleService.get(schedule.uuid)
        assert fired is not None
        self.assertGreater(fired.next_run_at, datetime.now(timezone.utc))
        self.assertIsNotNone(fired.last_run_at)

    async def test_each_fire_time_materializes_once(self):
        _ = await self._due_schedule()
        await asyncio.gather(
            self.scheduler._fire_due_schedules(), self.scheduler._fire_due_schedules()
        )
        await self.scheduler._fire_due_schedules()
        self.assertEqual(len(await db.list_by(Operation)), 1)

    async def test_a_schedule_with_an_active_run_is_not_stacked(self):
        schedule = await self._due_schedule()
        await self.scheduler._fire_due_schedules()
        async with db.transaction() as s:
            _ = await s.execute(
                update(OperationSchedule)
                .where(OperationSchedule.id == schedule.id)
                .values(next_run_at=datetime.now(timezone.utc) - timedelta(minutes=1))
            )

        await self.scheduler._fire_due_schedules()

        self.assertEqual(len(await db.list_by(Operation)), 1)
        fired = await OperationScheduleService.get(schedule.uuid)
        assert fired is not None
        self.assertGreater(fired.next_run_at, datetime.now(timezone.utc))

    async def test_schedules_sharing_a_cron_get_distinct_branches(self):
        _ = await self._due_schedule()
        _ = await self._due_schedule()
        await self.scheduler._fire_due_schedules()
        ops = await db.list_by(Operation)
        branches = {
            (await DatabaseService.get_session_context(op.session.uuid)).branch_name
            for op in ops
        }
        self.assertEqual(len(branches), 2)

    async def test_a_schedule_changed_after_it_was_read_is_not_fired(self):
        schedule = await self._due_schedule()
        [snapshot] = await OperationScheduleService.list_due(datetime.now(timezone.utc))
        await OperationScheduleService.update(schedule.id, {"enabled": False})

        await self.scheduler._fire(snapshot, datetime.now(timezone.utc))

        self.assertEqual(await db.list_by(Operation), [])

    async def test_an_owner_without_the_role_is_skipped(self):
        _ = await self._due_schedule()
        _ = await UserService.set_roles(
            self.user.id, operation_role=OperationRole.DEVELOPER, panel_role=None
        )
        await self.scheduler._fire_due_schedules()
        self.assertEqual(await db.list_by(Operation), [])

    async def test_stop_returns_promptly_when_idle(self):
        await self.scheduler.start()
        await asyncio.sleep(0.1)
        await asyncio.wait_for(self.scheduler.stop(), timeout=2)


class TestScheduledSlots(unittest.IsolatedAsyncioTestCase):
    """Cron runs never take the slots reserved for interactive calls."""

    async def test_slots_beyond_the_cap_claim_interactive_only(self):
        config = SchedulerConfig(
            concurrency=3, interactive_reserved_slots=1, claim_interval=0.01
        )
        release = asyncio.Event()
        flags: list[bool] = []
        queue = AsyncMock()

        async def claim(_worker_id: str, allow_scheduled: bool):
            flags.append(allow_scheduled)
            if allow_scheduled:
                return SimpleNamespace(schedule_id=1)
            return None

        async def execute(_op, _worker_id):
            _ = await release.wait()

        queue.claim.side_effect = claim
        executor = AsyncMock()
        executor.execute.side_effect = execute
        scheduler = OperationScheduler(
            queue=queue, executor=executor, submission=AsyncMock(), config=config
        )
        workers = [asyncio.create_task(scheduler._claim_loop(i)) for i in range(3)]
        await asyncio.sleep(0.1)

        self.assertEqual(executor.execute.await_count, 2)  # cap = 3 - 1
        self.assertEqual(flags[:2], [True, True])
        self.assertTrue(flags[2:])
        self.assertFalse(any(flags[2:]))

        scheduler._stopping.set()
        release.set()
        _ = await asyncio.gather(*workers)
        self.assertEqual(scheduler._scheduled_running, 0)
