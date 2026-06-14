# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import asyncio
import unittest
from unittest.mock import patch, AsyncMock
from uuid import uuid4

from fastapi.testclient import TestClient

from src.main import app
from src.domains.dto import PullRequestDTO
from src.domains.services.database_service import DatabaseService
from src.infrastructure.database.database import db
from src.infrastructure.database.models import Base


class TestCreatePR(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await db.initialize()
        async with db.session_manager.engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        self.client = TestClient(app)

    async def asyncTearDown(self):
        await db.close()

    def test_pr_creates_with_session_id_only(self):
        sid = uuid4()
        asyncio.run(
            DatabaseService.start_session(
                session_id=sid,
                user_id="u",
                repo_uri="https://example.com/foo.git",
                cloud="azure",
                environment="dev",
                branch_name="Nebula/feat-x",
            )
        )
        with patch(
            "src.api.v2.repository.GitUtils.create_pr",
            new=AsyncMock(return_value=PullRequestDTO(pr_id=42, status="open")),
        ):
            resp = self.client.put(
                "/v2/repository/pr",
                json={"session_id": str(sid), "q": "Add storage account"},
            )
        self.assertEqual(resp.status_code, 201, resp.text)
        body = resp.json()
        self.assertEqual(body["id"], 42)

        # Session should be marked completed
        row = asyncio.run(DatabaseService.load_session(str(sid)))
        self.assertEqual(row.status, "completed")

    def test_pr_unknown_session_returns_404(self):
        resp = self.client.put(
            "/v2/repository/pr",
            json={
                "session_id": "00000000-0000-0000-0000-000000000000",
                "q": "x",
            },
        )
        self.assertEqual(resp.status_code, 404, resp.text)
