# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import unittest
from uuid import uuid4

from src.domains.services.database_service import DatabaseService
from src.infrastructure.database.database import db
from src.infrastructure.database.models import Base


class TestStartSession(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await db.initialize()
        # Wipe between tests so per-test state is independent.
        async with db.session_manager.engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)

    async def asyncTearDown(self):
        await db.close()

    async def test_creates_active_row(self):
        sid = uuid4()
        await DatabaseService.start_session(
            session_id=sid,
            user_id="alice@example.com",
            repo_uri="https://example.com/foo.git",
            cloud="azure",
            environment="dev",
            branch_name="Nebula/2026-05-06_120000",
        )
        row = await DatabaseService.load_session(str(sid))
        self.assertEqual(row.user_id, "alice@example.com")
        self.assertEqual(row.repo_uri, "https://example.com/foo.git")
        self.assertEqual(row.branch_name, "Nebula/2026-05-06_120000")
        self.assertEqual(row.status, "active")
        self.assertFalse(row.in_flight)
        self.assertEqual(row.history, [])
        self.assertIsNone(row.last_payload)


class TestInFlightFlag(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await db.initialize()
        async with db.session_manager.engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        self.sid = uuid4()
        await DatabaseService.start_session(
            session_id=self.sid,
            user_id="u",
            repo_uri="https://example.com/a.git",
            cloud="azure",
            environment="dev",
            branch_name="Nebula/x",
        )

    async def asyncTearDown(self):
        await db.close()

    async def test_acquire_returns_true_when_free(self):
        ok = await DatabaseService.acquire_in_flight(str(self.sid))
        self.assertTrue(ok)
        row = await DatabaseService.load_session(str(self.sid))
        self.assertTrue(row.in_flight)

    async def test_acquire_returns_false_when_already_in_flight(self):
        await DatabaseService.acquire_in_flight(str(self.sid))
        ok = await DatabaseService.acquire_in_flight(str(self.sid))
        self.assertFalse(ok)

    async def test_release_clears_flag(self):
        await DatabaseService.acquire_in_flight(str(self.sid))
        await DatabaseService.release_in_flight(str(self.sid))
        row = await DatabaseService.load_session(str(self.sid))
        self.assertFalse(row.in_flight)


class TestAppendHistory(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await db.initialize()
        async with db.session_manager.engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        self.sid = uuid4()
        await DatabaseService.start_session(
            session_id=self.sid,
            user_id="u",
            repo_uri="https://example.com/a.git",
            cloud="azure",
            environment="dev",
            branch_name="Nebula/x",
        )

    async def asyncTearDown(self):
        await db.close()

    async def test_appends_turns_in_order(self):
        await DatabaseService.append_history(
            str(self.sid), {"user": "hi", "assistant": "hello"}
        )
        await DatabaseService.append_history(
            str(self.sid), {"user": "again", "assistant": "yes"}
        )
        row = await DatabaseService.load_session(str(self.sid))
        self.assertEqual(
            row.history,
            [
                {"user": "hi", "assistant": "hello"},
                {"user": "again", "assistant": "yes"},
            ],
        )


class TestSetLastPayload(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await db.initialize()
        async with db.session_manager.engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        self.sid = uuid4()
        await DatabaseService.start_session(
            session_id=self.sid,
            user_id="u",
            repo_uri="https://example.com/a.git",
            cloud="azure",
            environment="dev",
            branch_name="Nebula/x",
        )

    async def asyncTearDown(self):
        await db.close()

    async def test_overwrites_payload(self):
        await DatabaseService.set_last_payload(str(self.sid), {"v": 1})
        await DatabaseService.set_last_payload(str(self.sid), {"v": 2})
        row = await DatabaseService.load_session(str(self.sid))
        self.assertEqual(row.last_payload, {"v": 2})


class TestMarkCompleted(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await db.initialize()
        async with db.session_manager.engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        self.sid = uuid4()
        await DatabaseService.start_session(
            session_id=self.sid,
            user_id="u",
            repo_uri="https://example.com/a.git",
            cloud="azure",
            environment="dev",
            branch_name="Nebula/x",
        )

    async def asyncTearDown(self):
        await db.close()

    async def test_marks_completed(self):
        await DatabaseService.mark_completed(str(self.sid))
        row = await DatabaseService.load_session(str(self.sid))
        self.assertEqual(row.status, "completed")


class _ObservabilityBase(unittest.IsolatedAsyncioTestCase):
    """Shared setUp / tearDown for observability-column tests."""

    async def asyncSetUp(self):
        await db.initialize()
        async with db.session_manager.engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        self.sid = uuid4()
        await DatabaseService.start_session(
            session_id=self.sid,
            user_id="u",
            repo_uri="https://example.com/a.git",
            cloud="azure",
            environment="dev",
            branch_name="Nebula/x",
            operation_type="generate",
        )

    async def asyncTearDown(self):
        await db.close()


class TestStartSessionOperationType(_ObservabilityBase):
    async def test_operation_type_persisted(self):
        row = await DatabaseService.load_session(str(self.sid))
        self.assertEqual(row.operation_type, "generate")

    async def test_operation_type_drift(self):
        sid2 = uuid4()
        await DatabaseService.start_session(
            session_id=sid2,
            user_id="u",
            repo_uri="https://example.com/a.git",
            cloud="azure",
            environment="dev",
            branch_name="Nebula/y",
            operation_type="drift",
        )
        row = await DatabaseService.load_session(str(sid2))
        self.assertEqual(row.operation_type, "drift")

    async def test_apply_allowed_defaults_true(self):
        row = await DatabaseService.load_session(str(self.sid))
        self.assertTrue(row.apply_allowed)

    async def test_failure_reason_defaults_none(self):
        row = await DatabaseService.load_session(str(self.sid))
        self.assertIsNone(row.failure_reason)

    async def test_pull_request_url_defaults_none(self):
        row = await DatabaseService.load_session(str(self.sid))
        self.assertIsNone(row.pull_request_url)


class TestMarkFailed(_ObservabilityBase):
    async def test_stores_failure_reason(self):
        await DatabaseService.mark_failed(str(self.sid), "something went wrong")
        row = await DatabaseService.load_session(str(self.sid))
        self.assertEqual(row.failure_reason, "something went wrong")

    async def test_does_not_change_status(self):
        await DatabaseService.mark_failed(str(self.sid), "boom")
        row = await DatabaseService.load_session(str(self.sid))
        # Status must remain active — no `failed` terminal state in v1.
        self.assertEqual(row.status, "active")

    async def test_overwrites_previous_reason(self):
        await DatabaseService.mark_failed(str(self.sid), "first error")
        await DatabaseService.mark_failed(str(self.sid), "second error")
        row = await DatabaseService.load_session(str(self.sid))
        self.assertEqual(row.failure_reason, "second error")


class TestSetPullRequestUrl(_ObservabilityBase):
    async def test_persists_url(self):
        url = "https://github.com/org/repo/pull/42"
        await DatabaseService.set_pull_request_url(str(self.sid), url)
        row = await DatabaseService.load_session(str(self.sid))
        self.assertEqual(row.pull_request_url, url)

    async def test_overwrites_previous_url(self):
        await DatabaseService.set_pull_request_url(str(self.sid), "https://a.com/1")
        await DatabaseService.set_pull_request_url(str(self.sid), "https://a.com/2")
        row = await DatabaseService.load_session(str(self.sid))
        self.assertEqual(row.pull_request_url, "https://a.com/2")


class TestSetApplyAllowed(_ObservabilityBase):
    async def test_set_false(self):
        await DatabaseService.set_apply_allowed(str(self.sid), False)
        row = await DatabaseService.load_session(str(self.sid))
        self.assertFalse(row.apply_allowed)

    async def test_set_true_after_false(self):
        await DatabaseService.set_apply_allowed(str(self.sid), False)
        await DatabaseService.set_apply_allowed(str(self.sid), True)
        row = await DatabaseService.load_session(str(self.sid))
        self.assertTrue(row.apply_allowed)


class TestToggleApplyAllowed(_ObservabilityBase):
    async def test_toggle_false(self):
        await DatabaseService.toggle_apply_allowed(str(self.sid), False)
        row = await DatabaseService.load_session(str(self.sid))
        self.assertFalse(row.apply_allowed)

    async def test_toggle_true(self):
        await DatabaseService.toggle_apply_allowed(str(self.sid), False)
        await DatabaseService.toggle_apply_allowed(str(self.sid), True)
        row = await DatabaseService.load_session(str(self.sid))
        self.assertTrue(row.apply_allowed)
