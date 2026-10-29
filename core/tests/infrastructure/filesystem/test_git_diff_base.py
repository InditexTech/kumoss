# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Tests for the GitUtils diff base and revert_to.

An import round runs in batches, and each batch's agents must see only
the blocks that batch generated: the diff base narrows the branch diff to
the commits made on top of it. A batch whose configuration cannot be
generated is undone with revert_to, without rewriting the branch.

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


class TestDiffBase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.bare, self.work = _clone_on_a_session_branch(self.tmp)
        self.git = GitUtils(
            uri=f"file://{self.bare}",
            git_provider=GitProviderName.GITHUB,
            cwd=self.work,
        )

        await self.__commit("batch_1.tf", 'resource "null_resource" "one" {}\n')
        self.base = await self.git.get_head_commit()
        await self.__commit("batch_2.tf", 'resource "null_resource" "two" {}\n')

    async def asyncTearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    async def __commit(self, name: str, content: str) -> None:
        (self.work / name).write_text(content)
        await self.git.commit_and_push(_BRANCH)

    async def test_head_commit_is_the_checked_out_commit(self):
        self.assertEqual(
            await self.git.get_head_commit(), _git(self.work, "rev-parse", "HEAD")
        )

    async def test_branch_diff_starts_at_the_default_branch_by_default(self):
        diff = await self.git.show_diff(working_tree=False, full_content=False)

        self.assertIn("batch_1.tf", diff)
        self.assertIn("batch_2.tf", diff)

    async def test_diff_base_narrows_the_branch_diff_to_later_commits(self):
        self.git.set_diff_base(self.base)

        diff = await self.git.show_diff(working_tree=False, full_content=False)

        self.assertNotIn("batch_1.tf", diff)
        self.assertIn("batch_2.tf", diff)

    async def test_clearing_the_diff_base_restores_the_whole_branch(self):
        self.git.set_diff_base(self.base)
        self.git.set_diff_base(None)

        diff = await self.git.show_diff(working_tree=False, full_content=False)

        self.assertIn("batch_1.tf", diff)
        self.assertIn("batch_2.tf", diff)

    async def test_diff_base_leaves_working_tree_diffs_alone(self):
        self.git.set_diff_base(self.base)
        (self.work / "batch_1.tf").write_text("# edited\n")

        diff = await self.git.show_diff(working_tree=True, full_content=False)

        self.assertIn("batch_1.tf", diff)

    async def test_revert_undoes_later_commits_and_pushes(self):
        await self.git.revert_to(_BRANCH, self.base)

        self.assertTrue((self.work / "batch_1.tf").exists())
        self.assertFalse((self.work / "batch_2.tf").exists())
        # History is kept: the undo is a new commit, pushed without force.
        head = _git(self.work, "rev-parse", "HEAD")
        self.assertNotEqual(head, self.base)
        self.assertEqual(head, _git(self.bare, "rev-parse", _BRANCH))
        self.assertEqual(_git(self.work, "diff", self.base, "HEAD"), "")

    async def test_revert_to_head_is_a_no_op(self):
        head = await self.git.get_head_commit()

        await self.git.revert_to(_BRANCH, head)

        self.assertEqual(await self.git.get_head_commit(), head)


if __name__ == "__main__":
    unittest.main()
