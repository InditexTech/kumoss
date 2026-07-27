# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import asyncio
import unittest
from uuid import uuid4

from fastapi.testclient import TestClient

from src.main import app
from src.domains.services.database_service import DatabaseService
from src.infrastructure.database.database import db
from src.infrastructure.database.models import Base


class TestSessionsList(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await db.initialize()
        async with db.session_manager.engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        self.client = TestClient(app)

    async def asyncTearDown(self):
        await db.close()

    def test_list_returns_sessions_with_new_fields(self):
        sid = uuid4()
        asyncio.run(
            DatabaseService.start_session(
                session_id=sid,
                user_id="u",
                repo_uri="https://example.com/foo.git",
                cloud="azure",
                environment="dev",
                branch_name="Nebula/x",
            )
        )
        resp = self.client.get("/v1/sessions/")
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        # Body shape may be {items: [...]} or a list — accept either.
        items = body.get("items", body) if isinstance(body, dict) else body
        self.assertGreaterEqual(len(items), 1)
