# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import unittest
from contextlib import nullcontext
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from src.api.deps import get_current_user
from src.domains.entities import User
from src.infrastructure.exceptions import InvalidRepoURI
from src.infrastructure.filesystem.git.repo_uri_guard import REJECTED_MESSAGE
from src.main import app
from src.shared.constants import OperationRole
from src.shared.exceptions import ExceptionHandler

_GUARD = "src.infrastructure.filesystem.git.repo_uri_guard"


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
                json={"repo_uri": "https://github.com/org/missing.git"},
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

    def test_parse_accepts_a_username_only_uri(self):
        uri = "https://InditexData@dev.azure.com/InditexData/DevOpsv2/_git/repo"
        svc = _mock_service(AsyncMock(return_value=[]))
        with patch(
            "src.api.v1.repository.ApplicationFactory.get_iac_root_detection_service",
            return_value=svc,
        ):
            resp = self.client.post("/v1/repository/parse", json={"repo_uri": uri})
        self.assertEqual(resp.status_code, 200)
        svc.detect_roots.assert_awaited_once_with(uri)

    def test_parse_rejects_unsupported_transports_before_git(self):
        """vuln-0009: file://, http://, git:// and ext:: never reach git."""
        for uri in (
            "file:///etc/passwd",
            "http://core:8000/api/v1/auth/config",
            "http://redis:6379",
            "git://core:8000/x",
            "ext::sh%20-c%20id",
            "/etc/passwd",
            "--upload-pack=id",
        ):
            with (
                self.subTest(uri=uri),
                patch("src.infrastructure.filesystem.workspace.GitUtils") as git,
            ):
                resp = self.client.post("/v1/repository/parse", json={"repo_uri": uri})
                self.assertEqual(resp.status_code, 422, resp.text)
                git.assert_not_called()

    def test_parse_rejects_internal_hosts_with_a_generic_error(self):
        """vuln-0009: internal targets are refused before git runs, and the
        detail is identical for every target so it cannot be used as an oracle."""
        # None: an IP literal, resolved for real. Otherwise what DNS returns.
        internal = {
            "https://127.0.0.1:8000/api/v1/auth/config": None,
            "https://169.254.169.254/latest/meta-data/": None,
            "https://[::1]/x": None,
            "ssh://git@core:22/x": {"172.18.0.10"},
            "https://object-storage:9000": {"172.18.0.7"},
            "git@phoenix:repo.git": {"172.18.0.5"},
            "https://notifications:8080": OSError("Name or service not known"),
        }
        details = set()
        for uri, resolved in internal.items():
            resolve = (
                patch(f"{_GUARD}._resolve", AsyncMock(side_effect=[resolved]))
                if resolved is not None
                else nullcontext()
            )
            with (
                self.subTest(uri=uri),
                resolve,
                patch("src.infrastructure.filesystem.workspace.GitUtils") as git,
            ):
                resp = self.client.post("/v1/repository/parse", json={"repo_uri": uri})
                self.assertEqual(resp.status_code, 400, resp.text)
                git.assert_not_called()
                details.add(resp.json()["detail"])
        self.assertEqual(details, {REJECTED_MESSAGE})

    def test_parse_does_not_reflect_git_stderr(self):
        """vuln-0009: a failing ls-remote against an allowed host returns the
        generic message, not git's stderr."""
        stderr = "fatal: unable to access 'https://git.example.com/': Empty reply"
        with (
            patch(
                "src.infrastructure.filesystem.workspace.ensure_repo_uri_allowed",
                AsyncMock(),
            ),
            patch("src.infrastructure.filesystem.workspace.GitUtils") as git,
        ):
            git.return_value.ls_remote = AsyncMock(return_value=False)
            git.return_value.error_msg = stderr
            resp = self.client.post(
                "/v1/repository/parse",
                json={"repo_uri": "https://git.example.com/org/repo.git"},
            )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["detail"], REJECTED_MESSAGE)
        self.assertNotIn("Empty reply", resp.text)
