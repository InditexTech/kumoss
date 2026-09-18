# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Tests that GitUtils delegates create_pr/complete_pr to its injected
IGitProvider with the correct arguments, and that create_pr resolves
``base`` from the local clone's default branch.

GitUtils points at a file:// bare remote so the ``git ls-remote
--symref`` that ``create_pr`` uses to resolve ``base`` needs no network
access; ``repository_url`` is a separate argument and stays the
GitHub-shaped URL the provider would be called with. The provider
itself is replaced with an AsyncMock so we can assert on the call
arguments.
"""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from src.domains.dto import PullRequestDTO
from src.infrastructure.filesystem import GitUtils
from src.shared.constants import GitProviderName

_REPO_URL = "https://github.com/octo/widgets"


def _init_clone(tmp: Path, default_branch: str = "main") -> tuple[Path, str]:
    """Return (clone dir, file:// URI of its bare origin)."""
    bare = tmp / "remote.git"
    subprocess.check_call(["git", "init", "--bare", "-b", default_branch, str(bare)])
    work = tmp / "work"
    subprocess.check_call(["git", "init", "-b", default_branch, str(work)])
    (work / "README.md").write_text("init\n")
    subprocess.check_call(["git", "-C", str(work), "add", "."])
    subprocess.check_call(
        [
            "git",
            "-C",
            str(work),
            "-c",
            "user.email=t@t",
            "-c",
            "user.name=t",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-m",
            "init",
        ]
    )
    subprocess.check_call(
        ["git", "-C", str(work), "remote", "add", "origin", str(bare)]
    )
    subprocess.check_call(
        ["git", "-C", str(work), "push", "-u", "origin", default_branch]
    )

    clone = tmp / "clone"
    subprocess.check_call(["git", "clone", str(bare), str(clone)])
    return clone, f"file://{bare}"


class TestGitUtilsProviderDelegation(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.clone, self.uri = _init_clone(self.tmp, default_branch="main")
        self.git = GitUtils(
            uri=self.uri,
            git_provider=GitProviderName.GITHUB,
            cwd=self.clone,
        )
        # Replace the factory-built provider with an AsyncMock so we can
        # assert on delegation arguments without doing any HTTP.
        self.fake_provider = AsyncMock()
        self.git._GitUtils__provider = self.fake_provider

    async def asyncTearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    async def test_create_pr_forwards_args_and_resolves_base_from_default_branch(self):
        expected = PullRequestDTO(id=99, url="http://x", status="open")
        self.fake_provider.create_pr.return_value = expected

        result = await self.git.create_pr(
            repository_url=_REPO_URL,
            head_branch="Nebula/feature",
            title="My PR",
            description="Body",
        )

        self.assertIs(result, expected)
        self.fake_provider.create_pr.assert_awaited_once_with(
            repository_url=_REPO_URL,
            head="Nebula/feature",
            base="main",
            title="My PR",
            description="Body",
        )

    async def test_complete_pr_forwards_args(self):
        self.fake_provider.complete_pr.return_value = None
        await self.git.complete_pr(pr_id=42)
        self.fake_provider.complete_pr.assert_awaited_once_with(self.uri, 42)


class TestGitUtilsProviderDelegationMasterDefault(unittest.IsolatedAsyncioTestCase):
    """Same as above but the remote's default branch is ``master`` to
    confirm ``create_pr`` doesn't hard-code ``main``."""

    async def asyncSetUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.clone, self.uri = _init_clone(self.tmp, default_branch="master")
        self.git = GitUtils(
            uri=self.uri,
            git_provider=GitProviderName.GITHUB,
            cwd=self.clone,
        )
        self.fake_provider = AsyncMock()
        self.git._GitUtils__provider = self.fake_provider

    async def asyncTearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    async def test_create_pr_uses_master_when_remote_default_is_master(self):
        self.fake_provider.create_pr.return_value = PullRequestDTO(
            id=1, url="", status="open"
        )
        await self.git.create_pr(
            repository_url=_REPO_URL,
            head_branch="Nebula/feature",
            title="t",
            description="d",
        )
        _, kwargs = self.fake_provider.create_pr.call_args
        self.assertEqual(kwargs["base"], "master")


if __name__ == "__main__":
    unittest.main()
