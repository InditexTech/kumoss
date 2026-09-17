# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import unittest
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from src.api.deps import get_current_user
from src.domains.entities import User
from src.infrastructure.exceptions import InvalidRepoURI
from src.main import app
from src.shared.constants import OperationRole
from src.shared.exceptions import ExceptionHandler


def _mock_service(detect_roots: AsyncMock) -> MagicMock:
    svc = MagicMock()
    svc.detect_roots = detect_roots
    return svc


def _caller() -> User:
    return User(
        id=7,
        issuer="urn:test",
        subject="sub",
        email="dev@example.com",
        display_name="Dev",
        operation_role=OperationRole.DEVELOPER,
        panel_role=None,
        created_at=datetime.now(UTC),
    )


class TestParseRepository(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        app.dependency_overrides[get_current_user] = lambda: _caller()
        self.client = TestClient(app)

    async def asyncTearDown(self):
        app.dependency_overrides.clear()

    def test_parse_returns_roots(self):
        svc = _mock_service(AsyncMock(return_value=["infra/dev", "infra/pro"]))
        with patch(
            "src.api.v1.repository.ApplicationFactory.get_iac_root_detection_service",
            return_value=svc,
        ):
            resp = self.client.post(
                "/v1/repository/parse",
                json={"repo_uri": "https://github.com/org/repo.git"},
            )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["roots"], ["infra/dev", "infra/pro"])

    def test_parse_empty_repo_returns_empty_list(self):
        svc = _mock_service(AsyncMock(return_value=[]))
        with patch(
            "src.api.v1.repository.ApplicationFactory.get_iac_root_detection_service",
            return_value=svc,
        ):
            resp = self.client.post(
                "/v1/repository/parse",
                json={"repo_uri": "https://github.com/org/empty.git"},
            )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["roots"], [])

    def test_parse_invalid_uri_returns_400(self):
        svc = _mock_service(AsyncMock(side_effect=InvalidRepoURI("not a repo", 400)))
        with patch(
            "src.api.v1.repository.ApplicationFactory.get_iac_root_detection_service",
            return_value=svc,
        ):
            resp = self.client.post(
                "/v1/repository/parse",
                json={"repo_uri": "not-a-valid-url"},
            )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("not a repo", resp.json()["detail"])

    def test_parse_clone_failure_returns_502(self):
        svc = _mock_service(
            AsyncMock(side_effect=ExceptionHandler("clone failed", 502))
        )
        with patch(
            "src.api.v1.repository.ApplicationFactory.get_iac_root_detection_service",
            return_value=svc,
        ):
            resp = self.client.post(
                "/v1/repository/parse",
                json={"repo_uri": "https://github.com/org/broken.git"},
            )
        self.assertEqual(resp.status_code, 502)
        self.assertIn("clone failed", resp.json()["detail"])

    def test_parse_rejects_credentials_in_the_uri(self):
        svc = _mock_service(AsyncMock(return_value=[]))
        with patch(
            "src.api.v1.repository.ApplicationFactory.get_iac_root_detection_service",
            return_value=svc,
        ):
            resp = self.client.post(
                "/v1/repository/parse",
                json={"repo_uri": "https://user:ghp_secret@github.com/org/repo.git"},
            )
        self.assertEqual(resp.status_code, 422)
        svc.detect_roots.assert_not_awaited()

    def test_parse_bogus_uri_rejected_by_ls_remote(self):
        """Unmocked: a URI that fails git ls-remote produces a 400."""
        resp = self.client.post(
            "/v1/repository/parse",
            json={"repo_uri": "file:///nonexistent/repo.git"},
        )
        self.assertEqual(resp.status_code, 400)
