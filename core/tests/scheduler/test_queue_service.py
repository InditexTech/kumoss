# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Queue service tests — exercises enqueue, claim, heartbeat, complete,
fail, cancel, and reap using only DRIFT operations against a real Postgres.

Run from core/:
    pytest tests/scheduler/test_queue_service.py -v
"""

import unittest
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from src.domains.services.database_service import DatabaseService
from src.infrastructure.database import db
from src.infrastructure.database.models import Base
from src.infrastructure.redis import redis_client
from src.scheduler.config import SchedulerConfig
from src.scheduler.constants import OperationKind, OperationStatus
from src.scheduler.queue_service import OperationQueueService
from src.shared.constants import OperationType, TerraformProvider


class _QueueBase(unittest.IsolatedAsyncioTestCase):
    """Fresh DB + a session + a queue service per test."""

    async def asyncSetUp(self):
        await db.initialize()
        await redis_client.initialize()
        async with db.session_manager.engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)

        self.username = f"user-{uuid4().hex[:8]}@example.com"
        self.session_uuid = uuid4()
        await DatabaseService.create_session(
            session_id=self.session_uuid,
            user_id=self.username,
            operation=OperationType.DRIFT,
            repo_uri="https://example.com/repo.git",
            terraform_prv=TerraformProvider.AZURE,
            scope_id="sub-test",
            branch_name="Nebula/test",
            query="detect drift",
            iac_path="infra",
        )

        self.config = SchedulerConfig(
            concurrency=2,
            claim_interval=0.1,
            heartbeat_interval=1.0,
            lease_seconds=5.0,
            reaper_interval=1.0,
            schedule_poll_interval=1.0,
            default_max_attempts=2,
            retry_backoff_seconds=1.0,
            retry_backoff_cap=10.0,
            default_timeout_seconds=60,
            shutdown_grace_seconds=2.0,
        )
        self.queue = OperationQueueService(self.config)

    async def asyncTearDown(self):
        await redis_client.close()
        await db.close()


class TestEnqueue(_QueueBase):
    async def test_enqueue_creates_pending_operation(self):
        op = await self.queue.enqueue(
            session_uuid=self.session_uuid,
            kind=OperationKind.DRIFT,
            params={"q": "detect drift", "is_partial": False},
        )
        self.assertEqual(op.status, OperationStatus.PENDING)
        self.assertEqual(op.kind, OperationKind.DRIFT)
        self.assertEqual(op.attempt, 0)
        self.assertEqual(op.max_attempts, 2)
        self.assertIsNotNone(op.uuid)
        self.assertEqual(op.params["q"], "detect drift")

    async def test_enqueue_with_scheduled_at(self):
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        op = await self.queue.enqueue(
            session_uuid=self.session_uuid,
            kind=OperationKind.DRIFT,
            params={"q": "deferred drift"},
            scheduled_at=future,
        )
        self.assertGreater(op.scheduled_at, datetime.now(timezone.utc))

    async def test_enqueue_nonexistent_session_raises(self):
        with self.assertRaises(Exception):
            await self.queue.enqueue(
                session_uuid=uuid4(),
                kind=OperationKind.DRIFT,
                params={},
            )


class TestClaim(_QueueBase):
    async def test_claim_returns_operation(self):
        await self.queue.enqueue(
            session_uuid=self.session_uuid,
            kind=OperationKind.DRIFT,
            params={"q": "drift"},
        )
        op = await self.queue.claim("worker-1")
        self.assertIsNotNone(op)
        self.assertEqual(op.status, OperationStatus.RUNNING)
        self.assertEqual(op.attempt, 1)
        self.assertEqual(op.claimed_by, "worker-1")
        self.assertIsNotNone(op.lease_expires_at)
        self.assertIsNotNone(op.started_at)

    async def test_claim_empty_queue_returns_none(self):
        op = await self.queue.claim("worker-1")
        self.assertIsNone(op)

    async def test_claim_skips_future_scheduled(self):
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        await self.queue.enqueue(
            session_uuid=self.session_uuid,
            kind=OperationKind.DRIFT,
            params={"q": "future"},
            scheduled_at=future,
        )
        op = await self.queue.claim("worker-1")
        self.assertIsNone(op)

    async def test_two_claims_get_different_ops(self):
        """Two workers claiming at the same time get different operations
        thanks to FOR UPDATE SKIP LOCKED."""
        sid2 = uuid4()
        await DatabaseService.create_session(
            session_id=sid2,
            user_id=self.username,
            operation=OperationType.DRIFT,
            repo_uri="https://example.com/repo2.git",
            terraform_prv=TerraformProvider.AZURE,
            scope_id="sub-test-2",
            branch_name="Nebula/test2",
            query="drift 2",
            iac_path="infra",
        )
        await self.queue.enqueue(
            session_uuid=self.session_uuid,
            kind=OperationKind.DRIFT,
            params={"q": "drift 1"},
            dedup_key=f"drift:{self.session_uuid}",
        )
        await self.queue.enqueue(
            session_uuid=sid2,
            kind=OperationKind.DRIFT,
            params={"q": "drift 2"},
            dedup_key=f"drift:{sid2}",
        )

        op1 = await self.queue.claim("worker-1")
        op2 = await self.queue.claim("worker-2")

        self.assertIsNotNone(op1)
        self.assertIsNotNone(op2)
        self.assertNotEqual(op1.id, op2.id)


class TestHeartbeat(_QueueBase):
    async def test_heartbeat_extends_lease(self):
        await self.queue.enqueue(
            session_uuid=self.session_uuid,
            kind=OperationKind.DRIFT,
            params={"q": "drift"},
        )
        op = await self.queue.claim("worker-1")
        old_lease = op.lease_expires_at

        alive = await self.queue.heartbeat(op.id, "worker-1")
        self.assertTrue(alive)

        refreshed = await self.queue.get_operation(op.uuid)
        self.assertGreaterEqual(refreshed.lease_expires_at, old_lease)

    async def test_heartbeat_detects_cancel(self):
        await self.queue.enqueue(
            session_uuid=self.session_uuid,
            kind=OperationKind.DRIFT,
            params={"q": "drift"},
        )
        op = await self.queue.claim("worker-1")
        await self.queue.cancel(op.uuid)

        alive = await self.queue.heartbeat(op.id, "worker-1")
        self.assertFalse(alive)


class TestComplete(_QueueBase):
    async def test_complete_sets_succeeded(self):
        await self.queue.enqueue(
            session_uuid=self.session_uuid,
            kind=OperationKind.DRIFT,
            params={"q": "drift"},
        )
        op = await self.queue.claim("worker-1")
        await self.queue.complete(op.id)

        done = await self.queue.get_operation(op.uuid)
        self.assertEqual(done.status, OperationStatus.SUCCEEDED)
        self.assertIsNotNone(done.finished_at)
        self.assertIsNone(done.claimed_by)
        self.assertIsNone(done.lease_expires_at)


class TestFail(_QueueBase):
    async def test_fail_terminal(self):
        await self.queue.enqueue(
            session_uuid=self.session_uuid,
            kind=OperationKind.DRIFT,
            params={"q": "drift"},
        )
        op = await self.queue.claim("worker-1")
        await self.queue.fail(op.id, "something broke", retryable=False)

        failed = await self.queue.get_operation(op.uuid)
        self.assertEqual(failed.status, OperationStatus.FAILED)
        self.assertEqual(failed.error, "something broke")

    async def test_fail_retryable_requeues(self):
        await self.queue.enqueue(
            session_uuid=self.session_uuid,
            kind=OperationKind.DRIFT,
            params={"q": "drift"},
        )
        op = await self.queue.claim("worker-1")
        await self.queue.fail(op.id, "transient error", retryable=True)

        requeued = await self.queue.get_operation(op.uuid)
        self.assertEqual(requeued.status, OperationStatus.PENDING)
        self.assertGreater(requeued.scheduled_at, datetime.now(timezone.utc))
        self.assertIsNone(requeued.claimed_by)

    async def test_fail_retryable_exhausted_becomes_terminal(self):
        await self.queue.enqueue(
            session_uuid=self.session_uuid,
            kind=OperationKind.DRIFT,
            params={"q": "drift"},
            max_attempts=1,
        )
        op = await self.queue.claim("worker-1")
        await self.queue.fail(op.id, "still broken", retryable=True)

        failed = await self.queue.get_operation(op.uuid)
        self.assertEqual(failed.status, OperationStatus.FAILED)


class TestCancel(_QueueBase):
    async def test_cancel_pending(self):
        op = await self.queue.enqueue(
            session_uuid=self.session_uuid,
            kind=OperationKind.DRIFT,
            params={"q": "drift"},
        )
        await self.queue.cancel(op.uuid)

        cancelled = await self.queue.get_operation(op.uuid)
        self.assertEqual(cancelled.status, OperationStatus.CANCELLED)

    async def test_cancel_running_sets_flag(self):
        await self.queue.enqueue(
            session_uuid=self.session_uuid,
            kind=OperationKind.DRIFT,
            params={"q": "drift"},
        )
        op = await self.queue.claim("worker-1")
        await self.queue.cancel(op.uuid)

        flagged = await self.queue.get_operation(op.uuid)
        self.assertEqual(flagged.status, OperationStatus.RUNNING)
        self.assertTrue(flagged.cancel_requested)

    async def test_cancel_terminal_raises(self):
        await self.queue.enqueue(
            session_uuid=self.session_uuid,
            kind=OperationKind.DRIFT,
            params={"q": "drift"},
        )
        op = await self.queue.claim("worker-1")
        await self.queue.complete(op.id)

        with self.assertRaises(Exception):
            await self.queue.cancel(op.uuid)


class TestReaper(_QueueBase):
    async def test_reaper_requeues_expired_lease(self):
        op = await self.queue.enqueue(
            session_uuid=self.session_uuid,
            kind=OperationKind.DRIFT,
            params={"q": "drift"},
        )
        claimed = await self.queue.claim("dead-worker")

        # Manually expire the lease
        from sqlalchemy import update as sa_update
        from src.scheduler.models import Operation

        async with db.transaction() as session:
            stmt = (
                sa_update(Operation)
                .where(Operation.id == claimed.id)
                .values(
                    lease_expires_at=datetime.now(timezone.utc)
                    - timedelta(seconds=10)
                )
            )
            await session.execute(stmt)

        count = await self.queue.reap_expired_leases()
        self.assertEqual(count, 1)

        reaped = await self.queue.get_operation(op.uuid)
        self.assertEqual(reaped.status, OperationStatus.PENDING)

    async def test_reaper_fails_at_max_attempts(self):
        op = await self.queue.enqueue(
            session_uuid=self.session_uuid,
            kind=OperationKind.DRIFT,
            params={"q": "drift"},
            max_attempts=1,
        )
        claimed = await self.queue.claim("dead-worker")

        from sqlalchemy import update as sa_update
        from src.scheduler.models import Operation

        async with db.transaction() as session:
            stmt = (
                sa_update(Operation)
                .where(Operation.id == claimed.id)
                .values(
                    lease_expires_at=datetime.now(timezone.utc)
                    - timedelta(seconds=10)
                )
            )
            await session.execute(stmt)

        count = await self.queue.reap_expired_leases()
        self.assertEqual(count, 1)

        reaped = await self.queue.get_operation(op.uuid)
        self.assertEqual(reaped.status, OperationStatus.FAILED)
        self.assertIn("expired", reaped.error)
