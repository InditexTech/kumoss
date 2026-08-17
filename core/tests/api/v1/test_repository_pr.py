# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import asyncio
import unittest
from unittest.mock import patch, AsyncMock, MagicMock
from uuid import uuid4

from fastapi.testclient import TestClient

from src.main import app
from src.domains.dto import PullRequestDTO, PullRequestRef
from src.domains.services.database_service import DatabaseService
from src.infrastructure.database.database import db
from src.infrastructure.database.models import Base
from src.shared.exceptions import ExceptionHandler

_REPO_URI = "https://github.com/org/repo"


def _pr(number: int) -> PullRequestRef:
    return PullRequestRef(
        provider="GITHUB", url=f"{_REPO_URI}/pull/{number}", number=number
    )


def _mock_git_utils(complete_pr: AsyncMock) -> MagicMock:
    git = MagicMock()
    git.complete_pr = complete_pr
    return git


class TestMergePR(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = TestClient(app)
        self.ctx = MagicMock(repo_uri=_REPO_URI)

    def _merge(self, session_id: str = "00000000-0000-0000-0000-000000000001"):
        return self.client.patch(
            "/v1/repository/merge_pr", json={"session_id": session_id}
        )

    def test_merge_pr_merges_the_sessions_latest_pr(self):
        git = _mock_git_utils(AsyncMock(return_value=None))
        with (
            patch(
                "src.api.v1.repository.DatabaseService.get_session_context",
                new=AsyncMock(return_value=self.ctx),
            ),
            patch(
                "src.api.v1.repository.DatabaseService.get_pull_requests",
                new=AsyncMock(return_value=[_pr(7), _pr(42)]),
            ),
            patch(
                "src.api.v1.repository.ApplicationFactory.get_git_utils",
                return_value=git,
            ) as factory,
        ):
            resp = self._merge()
        self.assertEqual(resp.status_code, 200)
        factory.assert_called_once_with(_REPO_URI)
        git.complete_pr.assert_awaited_once_with(42)

    def test_merge_pr_unknown_session_returns_404(self):
        with patch(
            "src.api.v1.repository.DatabaseService.get_session_context",
            new=AsyncMock(side_effect=ExceptionHandler("Session not found.", 404)),
        ):
            resp = self._merge("00000000-0000-0000-0000-000000000000")
        self.assertEqual(resp.status_code, 404)

    def test_merge_pr_session_without_prs_returns_404(self):
        with (
            patch(
                "src.api.v1.repository.DatabaseService.get_session_context",
                new=AsyncMock(return_value=self.ctx),
            ),
            patch(
                "src.api.v1.repository.DatabaseService.get_pull_requests",
                new=AsyncMock(side_effect=ExceptionHandler("no pull requests", 404)),
            ),
        ):
            resp = self._merge()
        self.assertEqual(resp.status_code, 404)
        self.assertIn("no pull requests", resp.json()["detail"])

    def test_merge_pr_git_error_returns_status(self):
        git = _mock_git_utils(
            AsyncMock(side_effect=ExceptionHandler("merge conflict", 409))
        )
        with (
            patch(
                "src.api.v1.repository.DatabaseService.get_session_context",
                new=AsyncMock(return_value=self.ctx),
            ),
            patch(
                "src.api.v1.repository.DatabaseService.get_pull_requests",
                new=AsyncMock(return_value=[_pr(99)]),
            ),
            patch(
                "src.api.v1.repository.ApplicationFactory.get_git_utils",
                return_value=git,
            ),
        ):
            resp = self._merge()
        self.assertEqual(resp.status_code, 409)
        self.assertIn("merge conflict", resp.json()["detail"])


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
            "src.api.v1.repository.GitUtils.create_pr",
            new=AsyncMock(return_value=PullRequestDTO(pr_id=42, status="open")),
        ):
            resp = self.client.put(
                "/v1/repository/pr",
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
            "/v1/repository/pr",
            json={
                "session_id": "00000000-0000-0000-0000-000000000000",
                "q": "x",
            },
        )
        self.assertEqual(resp.status_code, 404, resp.text)
