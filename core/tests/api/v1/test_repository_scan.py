# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from src.infrastructure.filesystem.workspace import InvalidRepoURI
from src.main import app
from src.shared.exceptions import ExceptionHandler


class TestScanTerraformPaths(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = TestClient(app)

    def test_scan_returns_terraform_paths(self):
        with (
            patch(
                "src.api.v1.repository.WorkspaceService.validate_uri",
                new=AsyncMock(),
            ),
            patch(
                "src.api.v1.repository.WorkspaceService.scan_terraform_paths",
                new=AsyncMock(return_value=["infra/dev", "infra/pro"]),
            ),
        ):
            resp = self.client.post(
                "/v1/repository/scan",
                json={"repo_url": "https://github.com/org/repo.git"},
            )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["repo_url"], "https://github.com/org/repo.git")
        self.assertEqual(body["terraform_paths"], ["infra/dev", "infra/pro"])

    def test_scan_empty_repo_returns_empty_list(self):
        with (
            patch(
                "src.api.v1.repository.WorkspaceService.validate_uri",
                new=AsyncMock(),
            ),
            patch(
                "src.api.v1.repository.WorkspaceService.scan_terraform_paths",
                new=AsyncMock(return_value=[]),
            ),
        ):
            resp = self.client.post(
                "/v1/repository/scan",
                json={"repo_url": "https://github.com/org/empty.git"},
            )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["terraform_paths"], [])

    def test_scan_invalid_uri_returns_400(self):
        with patch(
            "src.api.v1.repository.WorkspaceService.validate_uri",
            new=AsyncMock(side_effect=InvalidRepoURI("not a repo")),
        ):
            resp = self.client.post(
                "/v1/repository/scan",
                json={"repo_url": "not-a-valid-url"},
            )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("not a repo", resp.json()["detail"])

    def test_scan_clone_failure_returns_error_code(self):
        with (
            patch(
                "src.api.v1.repository.WorkspaceService.validate_uri",
                new=AsyncMock(),
            ),
            patch(
                "src.api.v1.repository.WorkspaceService.scan_terraform_paths",
                new=AsyncMock(
                    side_effect=ExceptionHandler("clone failed", 422),
                ),
            ),
        ):
            resp = self.client.post(
                "/v1/repository/scan",
                json={"repo_url": "https://github.com/org/broken.git"},
            )
        self.assertEqual(resp.status_code, 422)
        self.assertIn("clone failed", resp.json()["detail"])
