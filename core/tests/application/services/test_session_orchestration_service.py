# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import unittest
from uuid import uuid4

from src.application.iac_requests import GenerateRequest
from src.application.services.session_orchestration_service import (
    SessionOrchestrationService,
)
from src.domains.services.database_service import DatabaseService
from src.infrastructure.database.database import db
from src.infrastructure.database.models import Base, User
from src.infrastructure.redis import redis_client
from src.shared.constants import OperationType, TerraformProvider


class TestSessionOrchestration(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await db.initialize()
        await redis_client.initialize()
        async with db.session_manager.engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        user = await db.create(
            User,
            issuer="urn:test",
            subject=f"sub-{uuid4().hex[:8]}",
            email=f"alice-{uuid4().hex[:8]}@example.com",
        )
        self.user_pk = user.id
        self.svc = SessionOrchestrationService()

    async def asyncTearDown(self):
        await redis_client.close()
        await db.close()

    def _first_request(self, **overrides) -> GenerateRequest:
        payload = {
            "repo_uri": "https://example.com/foo.git",
            "terraform_providers": "azure",
            "scope_id": "sub-123",
            "iac_path": "infra",
            "q": "hi",
        }
        payload.update(overrides)
        return GenerateRequest(**payload)

    async def test_first_call_creates_session_for_the_caller(self):
        ctx = await self.svc.resolve(
            self._first_request(), OperationType.GENERATE, self.user_pk
        )
        self.assertEqual(ctx.repo_uri, "https://example.com/foo.git")
        self.assertEqual(ctx.terraform_prv, TerraformProvider.AZURE)
        self.assertTrue(ctx.branch_name.startswith("Nebula/"))
        owner = await DatabaseService.get_session_owner(ctx.id)
        self.assertEqual(owner, self.user_pk)

    async def test_iteration_call_loads_the_session(self):
        ctx1 = await self.svc.resolve(
            self._first_request(), OperationType.GENERATE, self.user_pk
        )
        iter_req = GenerateRequest(session_id=str(ctx1.id), q="iterate")
        ctx2 = await self.svc.resolve(iter_req)
        self.assertEqual(ctx2.id, ctx1.id)
        self.assertEqual(ctx2.repo_uri, "https://example.com/foo.git")
        self.assertEqual(ctx2.branch_name, ctx1.branch_name)

    async def test_iac_path_persisted_and_loaded(self):
        ctx1 = await self.svc.resolve(
            self._first_request(iac_path="environments/dev"),
            OperationType.GENERATE,
            self.user_pk,
        )
        self.assertEqual(ctx1.iac_path, "environments/dev")

        iter_req = GenerateRequest(session_id=str(ctx1.id), q="iterate")
        ctx2 = await self.svc.resolve(iter_req)
        self.assertEqual(ctx2.iac_path, "environments/dev")
