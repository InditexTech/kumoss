# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import unittest

from src.application.iac_requests import GenerateRequest
from src.application.exceptions import (
    SessionConflict,
    SessionForbidden,
    SessionTerminal,
)
from src.application.services.session_orchestration_service import (
    SessionOrchestrationService,
)
from src.domains.services.database_service import DatabaseService
from src.infrastructure.database.database import db
from src.infrastructure.database.models import Base


class TestSessionOrchestration(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await db.initialize()
        async with db.session_manager.engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        self.svc = SessionOrchestrationService()

    async def asyncTearDown(self):
        await db.close()

    async def test_first_call_creates_session(self):
        req = GenerateRequest(
            repo_uri="https://example.com/foo.git",
            cloud="azure",
            environment="dev",
            user_id="alice",
            q="hi",
        )
        ctx = await self.svc.resolve(req)
        self.assertEqual(ctx.repo_uri, "https://example.com/foo.git")
        self.assertEqual(ctx.user_id, "alice")
        self.assertTrue(ctx.is_first_call)
        self.assertTrue(ctx.branch_name.startswith("Nebula/"))
        # In-flight is held.
        row = await DatabaseService.load_session(str(ctx.session_id))
        self.assertTrue(row.in_flight)

    async def test_iteration_call_loads_session(self):
        first = GenerateRequest(
            repo_uri="https://example.com/foo.git",
            cloud="azure",
            environment="dev",
            user_id="alice",
            q="hi",
        )
        ctx1 = await self.svc.resolve(first)
        await self.svc.release(ctx1.session_id)

        iter_req = GenerateRequest(
            session_id=str(ctx1.session_id), user_id="alice", q="iterate"
        )
        ctx2 = await self.svc.resolve(iter_req)
        self.assertEqual(ctx2.session_id, ctx1.session_id)
        self.assertFalse(ctx2.is_first_call)
        self.assertEqual(ctx2.repo_uri, "https://example.com/foo.git")
        self.assertEqual(ctx2.branch_name, ctx1.branch_name)

    async def test_iteration_with_conflicting_in_flight_raises(self):
        first = GenerateRequest(
            repo_uri="https://example.com/foo.git",
            cloud="azure",
            environment="dev",
            user_id="alice",
            q="hi",
        )
        ctx1 = await self.svc.resolve(first)
        # second resolve while first is in-flight
        iter_req = GenerateRequest(
            session_id=str(ctx1.session_id), user_id="alice", q="iterate"
        )
        with self.assertRaises(SessionConflict):
            await self.svc.resolve(iter_req)

    async def test_iteration_wrong_user_id_raises(self):
        first = GenerateRequest(
            repo_uri="https://example.com/foo.git",
            cloud="azure",
            environment="dev",
            user_id="alice",
            q="hi",
        )
        ctx1 = await self.svc.resolve(first)
        await self.svc.release(ctx1.session_id)

        iter_req = GenerateRequest(
            session_id=str(ctx1.session_id), user_id="mallory", q="iterate"
        )
        with self.assertRaises(SessionForbidden):
            await self.svc.resolve(iter_req)

    async def test_iac_path_persisted_and_loaded(self):
        """iac_path set on first call must survive round-trip to the iteration call."""
        first = GenerateRequest(
            repo_uri="https://example.com/foo.git",
            cloud="azure",
            environment="dev",
            user_id="alice",
            q="hi",
            iac_path="environments/dev",
        )
        ctx1 = await self.svc.resolve(first)
        self.assertEqual(ctx1.iac_path, "environments/dev")
        await self.svc.release(ctx1.session_id)

        iter_req = GenerateRequest(
            session_id=str(ctx1.session_id), user_id="alice", q="iterate"
        )
        ctx2 = await self.svc.resolve(iter_req)
        self.assertEqual(ctx2.iac_path, "environments/dev")
        self.assertFalse(ctx2.is_first_call)

    async def test_iteration_against_completed_raises(self):
        first = GenerateRequest(
            repo_uri="https://example.com/foo.git",
            cloud="azure",
            environment="dev",
            user_id="alice",
            q="hi",
        )
        ctx1 = await self.svc.resolve(first)
        await self.svc.release(ctx1.session_id)
        await DatabaseService.mark_completed(str(ctx1.session_id))

        iter_req = GenerateRequest(
            session_id=str(ctx1.session_id), user_id="alice", q="iterate"
        )
        with self.assertRaises(SessionTerminal):
            await self.svc.resolve(iter_req)
