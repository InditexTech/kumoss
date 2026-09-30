# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Tests for the GitUtils primitives: ls_remote, clone_repository and
push_branch.

These tests use a file:// bare repo so they run without network access.
"""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from src.infrastructure.filesystem import GitUtils
from src.shared.constants import GitProviderName

# The fixtures are local file:// remotes, which the repo_uri guard refuses;
# these tests exercise git itself, so bypass it (it has its own tests).
_guard = patch(
    "src.infrastructure.filesystem.git.git_utils.ensure_repo_uri_allowed",
    AsyncMock(return_value=()),
)


def setUpModule():
    _ = _guard.start()


def tearDownModule():
    _guard.stop()


_TMP_DIR = Path(tempfile.gettempdir())
_PROVIDER = GitProviderName.GITHUB


def _init_bare_remote(tmp: Path) -> tuple[Path, str]:
    """Create a bare repo with one commit. Return (bare_path, file:// URI)."""
    bare = tmp / "remote.git"
    subprocess.check_call(["git", "init", "--bare", "-b", "main", str(bare)])
    work = tmp / "work"
    subprocess.check_call(["git", "init", "-b", "main", str(work)])
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
            "commit",
            "-m",
            "init",
        ]
    )
    subprocess.check_call(
        ["git", "-C", str(work), "remote", "add", "origin", str(bare)]
    )
    subprocess.check_call(["git", "-C", str(work), "push", "origin", "main"])
    return bare, f"file://{bare}"


class TestLsRemote(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.bare, self.uri = _init_bare_remote(self.tmp)

    async def asyncTearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    async def test_returns_true_for_reachable_remote(self):
        git = GitUtils(uri=self.uri, git_provider=_PROVIDER, cwd=_TMP_DIR)
        result = await git.ls_remote()
        self.assertTrue(result)

    async def test_returns_false_for_bogus_remote(self):
        git = GitUtils(
            uri="file:///no/such/repo.git", git_provider=_PROVIDER, cwd=_TMP_DIR
        )
        result = await git.ls_remote()
        self.assertFalse(result)


class TestCloneRepositoryExtensions(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.bare, self.uri = _init_bare_remote(self.tmp)
        self.clone_root = self.tmp / "clones"
        self.clone_root.mkdir()

    async def asyncTearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    async def test_clone_without_branch_uses_default(self):
        git = GitUtils(uri=self.uri, git_provider=_PROVIDER, cwd=self.clone_root)
        ok = await git.clone_repository(
            repo_url=self.uri,
            repository_name="defaultclone",
        )
        self.assertTrue(ok)
        clone_dir = self.clone_root / "defaultclone"
        current = (
            subprocess.check_output(
                ["git", "-C", str(clone_dir), "branch", "--show-current"]
            )
            .decode()
            .strip()
        )
        self.assertEqual(current, "main")


class TestPushBranch(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.bare, self.uri = _init_bare_remote(self.tmp)
        self.clone_root = self.tmp / "clones"
        self.clone_root.mkdir()

    async def asyncTearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    async def test_push_branch_appears_on_origin(self):
        clone_name = "pushclone"
        git_clone = GitUtils(uri=self.uri, git_provider=_PROVIDER, cwd=self.clone_root)
        ok = await git_clone.clone_repository(
            repo_url=self.uri,
            repository_name=clone_name,
        )
        self.assertTrue(ok)

        clone_dir = self.clone_root / clone_name
        subprocess.check_call(
            ["git", "-C", str(clone_dir), "checkout", "-b", "Nebula/push-branch"]
        )
        # Make a commit so there's something to push
        (clone_dir / "new.txt").write_text("content\n")
        subprocess.check_call(["git", "-C", str(clone_dir), "add", "."])
        subprocess.check_call(
            [
                "git",
                "-C",
                str(clone_dir),
                "-c",
                "user.email=t@t",
                "-c",
                "user.name=t",
                "commit",
                "-m",
                "add file",
            ]
        )

        git_push = GitUtils(uri=self.uri, git_provider=_PROVIDER, cwd=clone_dir)
        pushed = await git_push.push_branch("Nebula/push-branch")
        self.assertTrue(pushed)

        # Verify the branch exists on the bare remote
        out = subprocess.check_output(
            ["git", "ls-remote", "--heads", self.uri, "Nebula/push-branch"]
        ).decode()
        self.assertIn("Nebula/push-branch", out)

    async def test_push_branch_returns_false_when_remote_missing(self):
        # Clone with no remote configured -> push should fail.
        clone_name = "noremote"
        empty = self.clone_root / clone_name
        subprocess.check_call(["git", "init", "-b", "main", str(empty)])
        (empty / "f.txt").write_text("x\n")
        subprocess.check_call(["git", "-C", str(empty), "add", "."])
        subprocess.check_call(
            [
                "git",
                "-C",
                str(empty),
                "-c",
                "user.email=t@t",
                "-c",
                "user.name=t",
                "commit",
                "-m",
                "init",
            ]
        )
        git = GitUtils(uri=self.uri, git_provider=_PROVIDER, cwd=empty)
        self.assertFalse(await git.push_branch("main"))
        self.assertTrue(git.error_msg)


if __name__ == "__main__":
    unittest.main()
