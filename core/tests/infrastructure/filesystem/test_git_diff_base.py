# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Tests for the GitUtils branch and working-tree diffs.

The branch diff (``working_tree=False``) spans every commit made on the
session branch since it left the default branch; the working-tree diff
(``working_tree=True``) shows only the uncommitted edits on top of HEAD.

These tests use a file:// bare repo so they run without network access.
"""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from src.infrastructure.filesystem import GitUtils
from src.shared.constants import GitProviderName

_BRANCH = "import/session-1"


def _git(cwd: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(cwd), *args]).decode().strip()


def _clone_on_a_session_branch(tmp: Path) -> tuple[Path, Path]:
    """Create a bare remote with one commit on main and a clone of it
    checked out on the session branch. Return (bare_path, clone_path)."""
    bare = tmp / "remote.git"
    seed = tmp / "seed"
    work = tmp / "work"
    subprocess.check_call(["git", "init", "-q", "--bare", "-b", "main", str(bare)])
    subprocess.check_call(["git", "init", "-q", "-b", "main", str(seed)])
    _git(seed, "config", "user.email", "t@t")
    _git(seed, "config", "user.name", "t")
    (seed / "main.tf").write_text("# root\n")
    _git(seed, "add", ".")
    _git(seed, "commit", "-q", "-m", "init")
    _git(seed, "push", "-q", str(bare), "main")

    subprocess.check_call(["git", "clone", "-q", str(bare), str(work)])
    _git(work, "config", "user.email", "t@t")
    _git(work, "config", "user.name", "t")
    _git(work, "checkout", "-q", "-b", _BRANCH)
    return bare, work


class TestShowDiff(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.bare, self.work = _clone_on_a_session_branch(self.tmp)
        self.git = GitUtils(
            uri=f"file://{self.bare}",
            git_provider=GitProviderName.GITHUB,
            cwd=self.work,
        )

        await self.__commit("batch_1.tf", 'resource "null_resource" "one" {}\n')
        await self.__commit("batch_2.tf", 'resource "null_resource" "two" {}\n')

    async def asyncTearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    async def __commit(self, name: str, content: str) -> None:
        (self.work / name).write_text(content)
        await self.git.commit_and_push(_BRANCH)

    async def test_commits_are_pushed_to_the_session_branch(self):
        self.assertEqual(
            _git(self.work, "rev-parse", "HEAD"),
            _git(self.bare, "rev-parse", _BRANCH),
        )

    async def test_branch_diff_spans_every_commit_since_the_default_branch(self):
        diff = await self.git.show_diff(working_tree=False, full_content=False)

        self.assertIn("batch_1.tf", diff)
        self.assertIn("batch_2.tf", diff)
        self.assertNotIn("main.tf", diff)

    async def test_working_tree_diff_shows_only_uncommitted_edits(self):
        (self.work / "batch_1.tf").write_text("# edited\n")

        diff = await self.git.show_diff(working_tree=True, full_content=False)

        self.assertIn("batch_1.tf", diff)
        self.assertNotIn("batch_2.tf", diff)

    async def test_a_clean_working_tree_has_no_diff(self):
        diff = await self.git.show_diff(working_tree=True, full_content=False)

        self.assertEqual(diff, "")


if __name__ == "__main__":
    unittest.main()
