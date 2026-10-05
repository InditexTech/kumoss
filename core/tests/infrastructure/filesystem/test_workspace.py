# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from src.infrastructure.exceptions import InvalidIacPath
from src.infrastructure.filesystem import (
    RepositoryUnreachable,
    WorkspaceService,
)
from src.shared.config import system_config

SESSION_PLAN_FILENAME = system_config.paths.session_plan_filename


def _init_bare_remote(tmp: Path, files: dict[str, str] | None = None) -> str:
    """Create a bare repo, push one commit into it, return file:// URI."""
    bare = tmp / "remote.git"
    subprocess.check_call(["git", "init", "--bare", "-b", "main", str(bare)])
    work = tmp / "work"
    subprocess.check_call(["git", "init", "-b", "main", str(work)])
    (work / "README.md").write_text("hi\n")
    for name, content in (files or {}).items():
        (work / name).write_text(content)
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
    return f"file://{bare}"


class TestValidateURI(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    async def asyncTearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    async def test_accepts_reachable_remote(self):
        uri = _init_bare_remote(self.tmp)
        await WorkspaceService().validate_uri(uri)  # no exception

    async def test_rejects_unreachable_remote_without_git_output(self):
        with self.assertRaises(RepositoryUnreachable) as ctx:
            await WorkspaceService().validate_uri("file:///nope/does-not-exist.git")
        self.assertEqual(ctx.exception.error_code, 400)
        self.assertEqual(
            ctx.exception.message,
            "Repository is not reachable or access was denied.",
        )


def _current_branch(path: Path) -> str:
    return (
        subprocess.check_output(["git", "-C", str(path), "branch", "--show-current"])
        .decode()
        .strip()
    )


def _commit_file(path: Path, name: str) -> None:
    (path / name).write_text("x\n")
    subprocess.check_call(["git", "-C", str(path), "add", "."])
    subprocess.check_call(
        [
            "git",
            "-C",
            str(path),
            "-c",
            "user.email=t@t",
            "-c",
            "user.name=t",
            "commit",
            "-m",
            name,
        ]
    )


class _WorkspaceBase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.uri = _init_bare_remote(self.tmp)
        self.workspaces = self.tmp / "workspaces"
        self.workspaces.mkdir()
        self.svc = WorkspaceService(base_path=self.workspaces)
        identity = patch.dict(
            os.environ,
            {
                "GIT_AUTHOR_NAME": "t",
                "GIT_AUTHOR_EMAIL": "t@t",
                "GIT_COMMITTER_NAME": "t",
                "GIT_COMMITTER_EMAIL": "t@t",
            },
        )
        identity.start()
        self.addCleanup(identity.stop)

    async def asyncTearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestSetupCallDir(_WorkspaceBase):
    async def test_first_call_clones_and_pushes_the_branch(self):
        sid = uuid4()
        path = await self.svc.setup_call_dir(
            session_id=sid, repo_uri=self.uri, branch="Kumoss/feat-x"
        )
        self.assertTrue(path.is_dir())
        self.assertTrue((path / ".git").is_dir())
        self.assertTrue((path / "README.md").is_file())
        self.assertEqual(path.parent, self.workspaces / str(sid))
        self.assertEqual(_current_branch(path), "Kumoss/feat-x")
        out = subprocess.check_output(
            ["git", "ls-remote", "--heads", self.uri, "Kumoss/feat-x"]
        ).decode()
        self.assertIn("Kumoss/feat-x", out)

    async def test_iteration_call_clones_existing_branch(self):
        sid = uuid4()
        first = await self.svc.setup_call_dir(
            session_id=sid, repo_uri=self.uri, branch="Kumoss/iter-x"
        )
        _commit_file(first, "new.txt")
        subprocess.check_call(
            ["git", "-C", str(first), "push", "origin", "Kumoss/iter-x"]
        )

        second = await self.svc.setup_call_dir(
            session_id=sid, repo_uri=self.uri, branch="Kumoss/iter-x"
        )
        self.assertNotEqual(first, second)
        self.assertEqual(_current_branch(second), "Kumoss/iter-x")
        self.assertTrue((second / "new.txt").is_file())


class TestTerraformGitignore(_WorkspaceBase):
    """Every workspace must carry the terraform ignores, and a project
    that ships its own .gitignore must keep the rules it had."""

    async def _clone_with(self, files: dict[str, str] | None = None) -> Path:
        remote = self.tmp / uuid4().hex
        remote.mkdir()
        return await self.svc.setup_call_dir(
            session_id=uuid4(),
            repo_uri=_init_bare_remote(remote, files),
            branch="Kumoss/ignores",
        )

    async def test_writes_the_template_when_the_repo_has_none(self):
        path = await self._clone_with()

        content = (path / ".gitignore").read_text()
        self.assertIn("INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)", content)
        self.assertIn("*_override.tf", content)

    async def test_appends_to_a_gitignore_the_project_owns(self):
        path = await self._clone_with({".gitignore": "node_modules/\n"})

        content = (path / ".gitignore").read_text()
        self.assertTrue(content.startswith("node_modules/\n"))
        self.assertIn("*_override.tf", content)


class TestCleanup(_WorkspaceBase):
    async def test_cleanup_removes_dir(self):
        path = await self.svc.setup_call_dir(
            session_id=uuid4(), repo_uri=self.uri, branch="Kumoss/cleanup"
        )
        self.svc.cleanup(path)
        self.assertFalse(path.exists())

    async def test_cleanup_idempotent_on_missing_dir(self):
        self.svc.cleanup(self.workspaces / "no-such-dir")  # no exception


class TestPinnedWorkspace(unittest.TestCase):
    """Pin lifecycle: promote a call dir into {base}/{sid}/pinned/."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.svc = WorkspaceService(base_path=self.tmp)
        self.sid = uuid4()

    def _make_clone(self, marker: str = "plan-bytes") -> Path:
        """Fake call dir holding the plan artifact at its root."""
        clone = self.tmp / str(self.sid) / str(uuid4())
        clone.mkdir(parents=True)
        (clone / SESSION_PLAN_FILENAME).write_text(marker)
        return clone

    def test_pin_renames_clone_into_pinned_slot(self):
        clone = self._make_clone()

        self.svc.pin_workspace(self.sid, clone)

        self.assertFalse(clone.exists())
        pinned = self.svc.pinned_dir(self.sid)
        self.assertEqual(pinned, self.tmp / str(self.sid) / "pinned")
        self.assertTrue((pinned / SESSION_PLAN_FILENAME).is_file())

    def test_pin_replaces_previous_slot(self):
        self.svc.pin_workspace(self.sid, self._make_clone(marker="old"))
        self.svc.pin_workspace(self.sid, self._make_clone(marker="new"))

        plan = self.svc.pinned_plan_path(self.sid)
        self.assertIsNotNone(plan)
        self.assertEqual(plan.read_text(), "new")

    def test_pinned_plan_path_none_without_pin(self):
        self.assertIsNone(self.svc.pinned_plan_path(self.sid))

    def test_pinned_plan_path_none_when_plan_file_missing(self):
        clone = self._make_clone()
        (clone / "iac" / SESSION_PLAN_FILENAME).unlink()
        self.svc.pin_workspace(self.sid, clone)

        self.assertIsNone(self.svc.pinned_plan_path(self.sid))

    def test_pin_survives_call_dir_cleanup(self):
        clone = self._make_clone()
        self.svc.pin_workspace(self.sid, clone)

        # The runner's finally always runs cleanup on the (now renamed)
        # call dir: it must be a harmless no-op for the pinned slot.
        self.svc.cleanup(clone)

        self.assertIsNotNone(self.svc.pinned_plan_path(self.sid))

    def test_discard_pinned_is_idempotent(self):
        self.svc.pin_workspace(self.sid, self._make_clone())

        self.svc.discard_pinned(self.sid)
        self.svc.discard_pinned(self.sid)  # no exception

        self.assertIsNone(self.svc.pinned_plan_path(self.sid))


class TestIacRoot(unittest.TestCase):
    """The IaC root resolves inside the clone, whatever the repo links to."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.svc = WorkspaceService(base_path=self.tmp)
        self.clone = self.tmp / "session" / "call"
        (self.clone / "envs" / "dev").mkdir(parents=True)
        (self.tmp / "session" / "other").mkdir()

    def test_subdirectory_and_repo_root(self):
        self.assertEqual(
            self.svc.iac_root(self.clone, "envs/dev"),
            (self.clone / "envs" / "dev").resolve(),
        )
        self.assertEqual(self.svc.iac_root(self.clone, None), self.clone.resolve())
        self.assertEqual(self.svc.iac_root(self.clone, ""), self.clone.resolve())

    def test_link_inside_the_clone_is_followed(self):
        (self.clone / "current").symlink_to("envs/dev")
        self.assertEqual(
            self.svc.iac_root(self.clone, "current"),
            (self.clone / "envs" / "dev").resolve(),
        )

    def test_links_leaving_the_clone_are_rejected(self):
        (self.clone / "root").symlink_to("/")
        (self.clone / "sibling").symlink_to("../other")
        for iac_path in ["root", "sibling", "root/etc"]:
            with self.assertRaises(InvalidIacPath, msg=iac_path):
                self.svc.iac_root(self.clone, iac_path)

    def test_missing_or_file_root_is_rejected(self):
        (self.clone / "main.tf").write_text("\n")
        for iac_path in ["nope", "main.tf"]:
            with self.assertRaises(InvalidIacPath, msg=iac_path):
                self.svc.iac_root(self.clone, iac_path)
