# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Operation queue state machine against a real Postgres."""

import unittest
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import update

from src.domains.exceptions import SessionConflict
from src.domains.services.database_service import DatabaseService
from src.domains.services.operation_queue_service import OperationQueueService
from src.domains.services.operation_schedule_service import OperationScheduleService
from src.domains.services.user_service import UserService
from src.domains.value_objects import TokenClaims
from src.infrastructure.database import db
from src.infrastructure.database.models import Base, Operation
from src.infrastructure.redis import redis_client
from src.shared.config.system_config import SchedulerConfig
from src.shared.constants import (
    OperationStatus,
    OperationType,
    SessionStatus,
    TerraformProvider,
)
from src.shared.exceptions import ExceptionHandler


class _QueueBase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await db.initialize()
        await redis_client.initialize()
        async with db.session_manager.engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        self.user = await UserService.resolve()
        self.session_id = await self._session(self.user.id)
        self.queue = OperationQueueService(
            SchedulerConfig(lease_seconds=5.0, default_timeout_seconds=60)
        )

    async def asyncTearDown(self):
        await redis_client.close()
        await db.close()

    async def _session(self, user_pk: int) -> UUID:
        sid = uuid4()
        _ = await DatabaseService.create_session(
            session_id=sid,
            user_pk=user_pk,
            operation=OperationType.DRIFT,
            repo_uri="https://example.com/repo.git",
            terraform_prv=TerraformProvider.AZURE,
            scope_id="sub-test",
            branch_name="Kumoss/test",
            query="detect drift",
            iac_path="infra",
        )
        return sid

    async def _enqueue(
        self, session_id: UUID | None = None, schedule_id: int | None = None
    ) -> Operation:
        return await self.queue.enqueue(
            session_id or self.session_id,
            OperationType.DRIFT,
            {"q": "drift"},
            schedule_id=schedule_id,
        )

    async def _schedule_pk(self) -> int:
        schedule = await OperationScheduleService.create(
            user_pk=self.user.id,
            name="nightly",
            kind=OperationType.DRIFT,
            cron="0 3 * * *",
            params={},
            enabled=True,
        )
        return schedule.id

    async def _reload(self, op: Operation) -> Operation:
        fresh = await db.get_by(Operation, id=op.id)
        assert fresh is not None
        return fresh


class TestEnqueue(_QueueBase):
    async def test_enqueue_creates_a_pending_operation(self):
        op = await self._enqueue()
        self.assertEqual(op.status, OperationStatus.PENDING)
        self.assertEqual(op.kind, OperationType.DRIFT)
        self.assertEqual(op.timeout_seconds, 60)

    async def test_apply_kind_is_storable(self):
        op = await self.queue.enqueue(self.session_id, OperationType.APPLY, {})
        self.assertEqual((await self._reload(op)).kind, OperationType.APPLY)

    async def test_unknown_session_is_404(self):
        with self.assertRaises(ExceptionHandler) as cm:
            _ = await self.queue.enqueue(uuid4(), OperationType.DRIFT, {})
        self.assertEqual(cm.exception.error_code, 404)

    async def test_second_active_operation_on_a_session_is_409(self):
        _ = await self._enqueue()
        with self.assertRaises(SessionConflict) as cm:
            _ = await self._enqueue()
        self.assertEqual(cm.exception.error_code, 409)

    async def test_a_finished_operation_frees_the_session(self):
        op = await self._enqueue()
        await self.queue.fail(op.id, "boom")
        again = await self._enqueue()
        self.assertEqual(again.status, OperationStatus.PENDING)


class TestClaim(_QueueBase):
    async def test_empty_queue_returns_none(self):
        self.assertIsNone(await self.queue.claim("w1"))

    async def test_claim_marks_running_with_a_lease(self):
        op = await self._enqueue()
        claimed = await self.queue.claim("w1")
        assert claimed is not None
        self.assertEqual(claimed.id, op.id)
        self.assertEqual(claimed.status, OperationStatus.RUNNING)
        self.assertEqual(claimed.claimed_by, "w1")
        self.assertIsNotNone(claimed.lease_expires_at)
        self.assertEqual(claimed.session.uuid, self.session_id)

    async def test_future_operations_are_not_claimed(self):
        op = await self._enqueue()
        async with db.transaction() as s:
            _ = await s.execute(
                update(Operation)
                .where(Operation.id == op.id)
                .values(scheduled_at=datetime.now(timezone.utc) + timedelta(hours=1))
            )
        self.assertIsNone(await self.queue.claim("w1"))

    async def test_two_claims_get_different_operations(self):
        _ = await self._enqueue()
        _ = await self._enqueue(await self._session(self.user.id))
        a = await self.queue.claim("w1")
        b = await self.queue.claim("w2")
        assert a is not None and b is not None
        self.assertNotEqual(a.id, b.id)
        self.assertIsNone(await self.queue.claim("w3"))

    async def test_interactive_operations_are_claimed_before_scheduled_ones(self):
        scheduled = await self._enqueue(schedule_id=await self._schedule_pk())
        interactive = await self._enqueue(await self._session(self.user.id))
        first = await self.queue.claim("w1")
        second = await self.queue.claim("w1")
        assert first is not None and second is not None
        self.assertEqual([first.id, second.id], [interactive.id, scheduled.id])

    async def test_scheduled_operations_can_be_excluded(self):
        _ = await self._enqueue(schedule_id=await self._schedule_pk())
        self.assertIsNone(await self.queue.claim("w1", allow_scheduled=False))
        self.assertIsNotNone(await self.queue.claim("w1"))

    async def test_active_operations_of_a_schedule(self):
        schedule_pk = await self._schedule_pk()
        self.assertFalse(await self.queue.has_active_for_schedule(schedule_pk))
        op = await self._enqueue(schedule_id=schedule_pk)
        self.assertTrue(await self.queue.has_active_for_schedule(schedule_pk))
        await self.queue.fail(op.id, "boom")
        self.assertFalse(await self.queue.has_active_for_schedule(schedule_pk))


class TestHeartbeat(_QueueBase):
    async def test_heartbeat_extends_the_lease(self):
        _ = await self._enqueue()
        op = await self.queue.claim("w1")
        assert op is not None
        self.assertTrue(await self.queue.heartbeat(op.id, "w1"))
        self.assertGreater(
            (await self._reload(op)).lease_expires_at, op.lease_expires_at
        )

    async def test_heartbeat_stops_on_cancel_request(self):
        _ = await self._enqueue()
        op = await self.queue.claim("w1")
        assert op is not None
        await self.queue.cancel(op)
        self.assertFalse(await self.queue.heartbeat(op.id, "w1"))

    async def test_heartbeat_from_another_worker_is_refused(self):
        _ = await self._enqueue()
        op = await self.queue.claim("w1")
        assert op is not None
        self.assertFalse(await self.queue.heartbeat(op.id, "w2"))


class TestFinish(_QueueBase):
    async def test_complete(self):
        _ = await self._enqueue()
        op = await self.queue.claim("w1")
        assert op is not None
        await self.queue.complete(op.id)
        done = await self._reload(op)
        self.assertEqual(done.status, OperationStatus.SUCCEEDED)
        self.assertIsNotNone(done.finished_at)
        self.assertIsNone(done.claimed_by)

    async def test_fail_is_terminal(self):
        _ = await self._enqueue()
        op = await self.queue.claim("w1")
        assert op is not None
        await self.queue.fail(op.id, "boom")
        failed = await self._reload(op)
        self.assertEqual(failed.status, OperationStatus.FAILED)
        self.assertEqual(failed.error, "boom")
        self.assertIsNone(await self.queue.claim("w1"))

    async def test_a_finished_operation_is_never_rewritten(self):
        op = await self._enqueue()
        await self.queue.cancel(op)
        await self.queue.complete(op.id)
        self.assertEqual((await self._reload(op)).status, OperationStatus.CANCELLED)


class TestFinishReleasesTheSession(_QueueBase):
    async def test_finishing_frees_in_flight_in_the_same_step(self):
        _ = await self._enqueue()
        op = await self.queue.claim("w1")
        assert op is not None
        await DatabaseService.acquire_in_flight(self.session_id)

        self.assertTrue(await self.queue.complete(op.id, release_session=True))

        summary = await DatabaseService.get_session_summary(self.session_id)
        self.assertFalse(summary.in_flight)

    async def test_a_late_finish_never_frees_a_successors_lock(self):
        op = await self._enqueue()
        await self.queue.fail(op.id, "reaped")
        await DatabaseService.acquire_in_flight(self.session_id)  # successor

        self.assertFalse(await self.queue.complete(op.id, release_session=True))

        summary = await DatabaseService.get_session_summary(self.session_id)
        self.assertTrue(summary.in_flight)


class TestCancel(_QueueBase):
    async def test_cancel_pending_is_immediate(self):
        op = await self._enqueue()
        await self.queue.cancel(op)
        self.assertEqual((await self._reload(op)).status, OperationStatus.CANCELLED)

    async def test_cancel_pending_ends_a_session_that_never_ran(self):
        await self.queue.cancel(await self._enqueue())
        last = await DatabaseService.get_last_status(self.session_id)
        self.assertIs(last.status, SessionStatus.FAILED)

    async def test_cancel_pending_keeps_a_session_that_already_ran(self):
        await DatabaseService.mark_completed(self.session_id, "round 1")
        await self.queue.cancel(await self._enqueue())
        last = await DatabaseService.get_last_status(self.session_id)
        self.assertIs(last.status, SessionStatus.COMPLETED)

    async def test_cancel_running_only_flags_it(self):
        _ = await self._enqueue()
        op = await self.queue.claim("w1")
        assert op is not None
        await self.queue.cancel(op)
        flagged = await self._reload(op)
        self.assertEqual(flagged.status, OperationStatus.RUNNING)
        self.assertTrue(flagged.cancel_requested)

    async def test_running_apply_and_import_cannot_be_cancelled(self):
        for kind in (OperationType.APPLY, OperationType.IMPORT):
            with self.subTest(kind=kind):
                sid = await self._session(self.user.id)
                _ = await self.queue.enqueue(sid, kind, {})
                op = await self.queue.claim("w1")
                assert op is not None
                with self.assertRaises(ExceptionHandler) as cm:
                    await self.queue.cancel(op)
                self.assertEqual(cm.exception.error_code, 409)
                self.assertFalse((await self._reload(op)).cancel_requested)

    async def test_cancel_finished_is_409(self):
        op = await self._enqueue()
        await self.queue.fail(op.id, "boom")
        with self.assertRaises(ExceptionHandler) as cm:
            await self.queue.cancel(await self._reload(op))
        self.assertEqual(cm.exception.error_code, 409)


class TestReaper(_QueueBase):
    async def test_expired_lease_fails_the_operation_and_frees_the_session(self):
        _ = await self._enqueue()
        op = await self.queue.claim("w1")
        assert op is not None
        await DatabaseService.acquire_in_flight(self.session_id)
        async with db.transaction() as s:
            _ = await s.execute(
                update(Operation)
                .where(Operation.id == op.id)
                .values(
                    lease_expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)
                )
            )

        self.assertEqual(await self.queue.reap_expired_leases(), 1)

        reaped = await self._reload(op)
        self.assertEqual(reaped.status, OperationStatus.FAILED)
        self.assertIsNone(await self.queue.claim("w1"))  # no retry
        last = await DatabaseService.get_last_status(self.session_id)
        self.assertIs(last.status, SessionStatus.FAILED)
        detail = await DatabaseService.get_session_summary(self.session_id)
        self.assertFalse(detail.in_flight)

    async def test_live_leases_are_left_alone(self):
        _ = await self._enqueue()
        _ = await self.queue.claim("w1")
        self.assertEqual(await self.queue.reap_expired_leases(), 0)


class TestList(_QueueBase):
    async def test_only_the_owners_operations_are_listed(self):
        mine = await self._enqueue()
        other = await UserService.resolve(
            TokenClaims(
                issuer="urn:test", subject="o", email="o@example.com", name=None
            )
        )
        _ = await self._enqueue(await self._session(other.id))

        items, total = await self.queue.list_operations(user_pk=self.user.id)
        self.assertEqual(total, 1)
        self.assertEqual([op.id for op in items], [mine.id])

    async def test_filters(self):
        op = await self._enqueue()
        second = await self._session(self.user.id)
        _ = await self.queue.enqueue(second, OperationType.APPLY, {})

        items, total = await self.queue.list_operations(
            user_pk=self.user.id, session_id=self.session_id
        )
        self.assertEqual((total, [i.id for i in items]), (1, [op.id]))
        items, total = await self.queue.list_operations(
            user_pk=self.user.id, kind=OperationType.APPLY
        )
        self.assertEqual(total, 1)
        self.assertEqual(items[0].session.uuid, second)
        _, total = await self.queue.list_operations(
            user_pk=self.user.id, status=OperationStatus.RUNNING
        )
        self.assertEqual(total, 0)
