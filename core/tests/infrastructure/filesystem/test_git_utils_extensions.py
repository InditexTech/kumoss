# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Tests for the new GitUtils primitives: ls_remote, push_branch,
and the extended clone_repository (depth + create_branch).

These tests use a file:// bare repo so they run without network access.
"""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from src.infrastructure.filesystem.git_utils import GitUtils

_TMP_DIR = Path(tempfile.gettempdir())


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
        git = GitUtils(cwd=_TMP_DIR)
        result = await git.ls_remote(self.uri)
        self.assertTrue(result)

    async def test_returns_false_for_bogus_remote(self):
        git = GitUtils(cwd=_TMP_DIR)
        result = await git.ls_remote("file:///no/such/repo.git")
        self.assertFalse(result)


class TestCloneRepositoryExtensions(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.bare, self.uri = _init_bare_remote(self.tmp)
        self.clone_root = self.tmp / "clones"
        self.clone_root.mkdir()

    async def asyncTearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    async def test_clone_with_depth_and_create_branch(self):
        git = GitUtils(cwd=self.clone_root)
        clone_name = "myclone"
        ok = await git.clone_repository(
            repo_url=self.uri,
            repository_name=clone_name,
            branch="Nebula/new-feat",
            depth=1,
            create_branch=True,
        )
        self.assertTrue(ok)
        clone_dir = self.clone_root / clone_name
        self.assertTrue(clone_dir.is_dir())
        current = (
            subprocess.check_output(
                ["git", "-C", str(clone_dir), "branch", "--show-current"]
            )
            .decode()
            .strip()
        )
        self.assertEqual(current, "Nebula/new-feat")


class TestPushBranch(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.bare, self.uri = _init_bare_remote(self.tmp)
        self.clone_root = self.tmp / "clones"
        self.clone_root.mkdir()

    async def asyncTearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    async def test_push_branch_appears_on_origin(self):
        # Clone + create branch
        clone_name = "pushclone"
        git_clone = GitUtils(cwd=self.clone_root)
        ok = await git_clone.clone_repository(
            repo_url=self.uri,
            repository_name=clone_name,
            branch="Nebula/push-branch",
            depth=1,
            create_branch=True,
        )
        self.assertTrue(ok)

        clone_dir = self.clone_root / clone_name
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

        git_push = GitUtils(cwd=clone_dir)
        pushed = await git_push.push_branch("Nebula/push-branch")
        self.assertTrue(pushed)

        # Verify the branch exists on the bare remote
        out = subprocess.check_output(
            ["git", "ls-remote", "--heads", self.uri, "Nebula/push-branch"]
        ).decode()
        self.assertIn("Nebula/push-branch", out)
