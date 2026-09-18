# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Tests for GitUtils.get_workspace_revision against a real repo.

This fingerprint is what decides whether a plan artifact still describes
the code on disk, so the two properties that matter pull in opposite
directions and both are asserted here: it must not move for the engine's
own output (the plan file the plan job just wrote, a provider cache that
keeps growing), or every ref would be stale the moment it was taken; and
it must move for any change to the code — staged, unstaged, untracked or
committed — or a stale plan would be read as current.

The engine's output is kept out of it by the ignore rules the workspace
adapter writes into every clone, so the repo under test gets that same
shipped file rather than rules of its own.
"""

import inspect
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from src.infrastructure.filesystem import GitUtils, WorkspaceService
from src.shared.constants import GitProviderName


_PROVIDER = GitProviderName.GITHUB

_SHIPPED_IGNORE = Path(inspect.getfile(WorkspaceService)).parent / "terraform.gitignore"


def _git(work: Path, *args: str) -> None:
    subprocess.check_call(
        [
            "git",
            "-C",
            str(work),
            "-c",
            "user.email=t@t",
            "-c",
            "user.name=t",
            *args,
        ]
    )


class TestGetWorkspaceRevision(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.work = self.tmp / "work"
        self.work.mkdir()
        subprocess.check_call(["git", "init", "-b", "main", str(self.work)])
        (self.work / "main.tf").write_text('resource "null_resource" "a" {}\n')
        _ = (self.work / ".gitignore").write_text(
            _SHIPPED_IGNORE.read_text(encoding="utf-8"), encoding="utf-8"
        )
        _git(self.work, "add", ".")
        _git(self.work, "commit", "-m", "init")
        self.git = GitUtils(
            uri="file:///unused.git", git_provider=_PROVIDER, cwd=self.work
        )

    async def asyncTearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    async def test_revision_is_a_stable_digest(self):
        first = await self.git.get_workspace_revision()
        second = await self.git.get_workspace_revision()

        self.assertEqual(first, second)
        self.assertRegex(first, r"^[0-9a-f]{64}$")

    async def test_rewriting_an_untracked_artifact_does_not_move_it(self):
        plan = self.work / "session.plan"
        _ = plan.write_bytes(b"binary plan v1")
        before = await self.git.get_workspace_revision()

        _ = plan.write_bytes(b"binary plan v2, longer than the first one")
        after = await self.git.get_workspace_revision()

        # A plan sampled after `plan -out` wrote its file must still match
        # when the next round overwrites that same file.
        self.assertEqual(before, after)

    async def test_a_growing_provider_cache_does_not_move_it(self):
        cache = self.work / ".terraform" / "providers" / "registry"
        cache.mkdir(parents=True)
        (cache / "provider-v1").write_text("binary")
        before = await self.git.get_workspace_revision()

        (cache / "provider-v2").write_text("binary")
        (cache / "nested").mkdir()
        (cache / "nested" / "lock").write_text("")
        after = await self.git.get_workspace_revision()

        # `**/.terraform/*` is ignored, so whatever init keeps downloading
        # there stays invisible however deep it goes.
        self.assertEqual(before, after)

    async def test_a_new_untracked_file_moves_it(self):
        before = await self.git.get_workspace_revision()

        (self.work / "storage.tf").write_text('resource "null_resource" "b" {}\n')
        after = await self.git.get_workspace_revision()

        # Generated code lands untracked: this is the change a plan must
        # not be reused across.
        self.assertNotEqual(before, after)

    async def test_a_file_added_to_an_untracked_directory_moves_it(self):
        module = self.work / "modules" / "network"
        module.mkdir(parents=True)
        (module / "main.tf").write_text('resource "null_resource" "c" {}\n')
        before = await self.git.get_workspace_revision()

        (module / "variables.tf").write_text('variable "name" {}\n')
        after = await self.git.get_workspace_revision()

        # `status` collapses an untracked directory to a single entry by
        # default, which would hide every file generated into a module
        # directory after the first one; the digest asks for untracked
        # paths individually so it cannot.
        self.assertNotEqual(before, after)

    async def test_editing_a_tracked_file_moves_it(self):
        before = await self.git.get_workspace_revision()

        (self.work / "main.tf").write_text('resource "null_resource" "edited" {}\n')
        after = await self.git.get_workspace_revision()

        self.assertNotEqual(before, after)

    async def test_staging_a_change_moves_it(self):
        (self.work / "storage.tf").write_text('resource "null_resource" "b" {}\n')
        untracked = await self.git.get_workspace_revision()

        _git(self.work, "add", "storage.tf")
        staged = await self.git.get_workspace_revision()

        self.assertNotEqual(untracked, staged)

    async def test_committing_moves_it(self):
        clean = await self.git.get_workspace_revision()
        (self.work / "storage.tf").write_text('resource "null_resource" "b" {}\n')
        _git(self.work, "add", "storage.tf")
        dirty = await self.git.get_workspace_revision()

        _git(self.work, "commit", "-m", "add storage")
        committed = await self.git.get_workspace_revision()

        # A commit leaves a clean tree again, so only the branch oid the
        # --branch header carries tells the two clean states apart.
        self.assertNotIn(committed, (clean, dirty))


if __name__ == "__main__":
    unittest.main()
