# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import unittest
from datetime import UTC, datetime
from unittest.mock import patch, AsyncMock, MagicMock

from fastapi.testclient import TestClient

from src.api.deps import get_current_user
from src.domains.entities import User
from src.main import app
from src.domains.dto import PullRequestDTO, PullRequestRef
from src.shared.constants import OperationRole
from src.shared.exceptions import ExceptionHandler

_REPO_URI = "https://github.com/org/repo"
_SID = "00000000-0000-0000-0000-000000000001"


def _caller(pk: int = 7) -> User:
    return User(
        id=pk,
        issuer="urn:test",
        subject="sub",
        email="dev@example.com",
        display_name="Dev",
        operation_role=OperationRole.DEVELOPER,
        panel_role=None,
        created_at=datetime.now(UTC),
    )


def _pr(number: int) -> PullRequestRef:
    return PullRequestRef(
        provider="GITHUB", url=f"{_REPO_URI}/pull/{number}", number=number
    )


def _mock_git_utils(complete_pr: AsyncMock) -> MagicMock:
    git = MagicMock()
    git.complete_pr = complete_pr
    return git


class _EndpointBase(unittest.IsolatedAsyncioTestCase):
    """Mock-based endpoint tests: identity injected, DB patched away."""

    async def asyncSetUp(self):
        app.dependency_overrides[get_current_user] = lambda: _caller()
        self.client = TestClient(app)
        self.ctx = MagicMock(repo_uri=_REPO_URI)
        self._owner = patch(
            "src.api.deps.DatabaseService.get_session_owner",
            new=AsyncMock(return_value=7),
        )
        self._owner.start()

    async def asyncTearDown(self):
        self._owner.stop()
        app.dependency_overrides.clear()


class TestMergePR(_EndpointBase):
    def _merge(self, session_id: str = _SID):
        return self.client.put(
            "/v1/repository/pr/merge", json={"session_id": session_id}
        )

    def test_merge_pr_merges_the_sessions_latest_pr(self):
        git = _mock_git_utils(AsyncMock(return_value=None))
        with (
            patch(
                "src.api.v1.repository.DatabaseService.get_session_context",
                new=AsyncMock(return_value=self.ctx),
            ),
            patch(
                "src.api.v1.repository.DatabaseService.is_session_blocked",
                new=AsyncMock(return_value=False),
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
        self.assertEqual(resp.status_code, 204, resp.text)
        factory.assert_called_once_with(_REPO_URI)
        git.complete_pr.assert_awaited_once_with(42)

    def test_merge_pr_unknown_session_returns_404(self):
        with patch(
            "src.api.deps.DatabaseService.get_session_owner",
            new=AsyncMock(side_effect=ExceptionHandler("Session not found.", 404)),
        ):
            resp = self._merge("00000000-0000-0000-0000-000000000000")
        self.assertEqual(resp.status_code, 404)

    def test_merge_pr_not_the_owner_returns_403(self):
        with patch(
            "src.api.deps.DatabaseService.get_session_owner",
            new=AsyncMock(return_value=8),
        ):
            resp = self._merge()
        self.assertEqual(resp.status_code, 403)

    def test_merge_pr_blocked_session_returns_409(self):
        with (
            patch(
                "src.api.v1.repository.DatabaseService.get_session_context",
                new=AsyncMock(return_value=self.ctx),
            ),
            patch(
                "src.api.v1.repository.DatabaseService.is_session_blocked",
                new=AsyncMock(return_value=True),
            ),
        ):
            resp = self._merge()
        self.assertEqual(resp.status_code, 409)

    def test_merge_pr_session_without_prs_returns_404(self):
        with (
            patch(
                "src.api.v1.repository.DatabaseService.get_session_context",
                new=AsyncMock(return_value=self.ctx),
            ),
            patch(
                "src.api.v1.repository.DatabaseService.is_session_blocked",
                new=AsyncMock(return_value=False),
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
                "src.api.v1.repository.DatabaseService.is_session_blocked",
                new=AsyncMock(return_value=False),
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


class TestCreatePR(_EndpointBase):
    def test_pr_creates_with_session_id_only(self):
        pr_svc = MagicMock()
        pr_svc.create_pr = AsyncMock(
            return_value=PullRequestDTO(
                id=42, url=f"{_REPO_URI}/pull/42", status="open"
            )
        )
        factory = MagicMock()
        factory.return_value.get_pull_request_service.return_value = pr_svc
        with (
            patch(
                "src.api.v1.repository.DatabaseService.get_session_context",
                new=AsyncMock(return_value=self.ctx),
            ),
            patch("src.api.v1.repository.ApplicationFactory", factory),
            patch("src.api.v1.repository.PhoenixTracer", MagicMock()),
        ):
            resp = self.client.put("/v1/repository/pr", json={"session_id": _SID})
        self.assertEqual(resp.status_code, 201, resp.text)
        body = resp.json()
        self.assertEqual(body["id"], 42)
        self.assertEqual(body["status"], "open")

    def test_pr_unknown_session_returns_404(self):
        with patch(
            "src.api.deps.DatabaseService.get_session_owner",
            new=AsyncMock(side_effect=ExceptionHandler("Session not found.", 404)),
        ):
            resp = self.client.put(
                "/v1/repository/pr",
                json={"session_id": "00000000-0000-0000-0000-000000000000"},
            )
        self.assertEqual(resp.status_code, 404, resp.text)
