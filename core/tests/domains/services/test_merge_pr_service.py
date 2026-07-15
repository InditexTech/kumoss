# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from src.domains.services.merge_pr_service import MergePullRequestService
from src.shared.exceptions import ExceptionHandler


def _mock_git(complete_pr: AsyncMock) -> MagicMock:
    git = MagicMock()
    git.complete_pr = complete_pr
    return git


class TestMergePullRequestService(unittest.IsolatedAsyncioTestCase):
    async def test_merge_succeeds(self):
        git = _mock_git(AsyncMock(return_value=None))
        session = SimpleNamespace(repo_uri="https://github.com/org/repo.git")
        with patch(
            "src.domains.services.merge_pr_service.DatabaseService.get_session",
            new=AsyncMock(return_value=session),
        ):
            svc = MergePullRequestService(git=git)
            await svc.merge("sid-1", 42)
        git.complete_pr.assert_awaited_once_with(
            "https://github.com/org/repo.git", 42
        )

    async def test_merge_unknown_session_raises_404(self):
        git = _mock_git(AsyncMock())
        with patch(
            "src.domains.services.merge_pr_service.DatabaseService.get_session",
            new=AsyncMock(return_value=None),
        ):
            svc = MergePullRequestService(git=git)
            with self.assertRaises(ExceptionHandler) as ctx:
                await svc.merge("missing-id", 1)
        self.assertEqual(ctx.exception.error_code, 404)
        git.complete_pr.assert_not_awaited()

    async def test_merge_git_error_propagates(self):
        git = _mock_git(
            AsyncMock(side_effect=ExceptionHandler("merge conflict", 409))
        )
        session = SimpleNamespace(repo_uri="https://github.com/org/repo.git")
        with patch(
            "src.domains.services.merge_pr_service.DatabaseService.get_session",
            new=AsyncMock(return_value=session),
        ):
            svc = MergePullRequestService(git=git)
            with self.assertRaises(ExceptionHandler) as ctx:
                await svc.merge("sid-1", 99)
        self.assertEqual(ctx.exception.error_code, 409)
