# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from src.infrastructure.filesystem import (
    WorkspaceService,
    InvalidRepoURI,
)
from src.shared.config import system_config

SESSION_PLAN_FILENAME = system_config.paths.session_plan_filename


def _init_bare_remote(tmp: Path) -> str:
    """Create a bare repo, push one commit into it, return file:// URI."""
    bare = tmp / "remote.git"
    subprocess.check_call(["git", "init", "--bare", "-b", "main", str(bare)])
    work = tmp / "work"
    subprocess.check_call(["git", "init", "-b", "main", str(work)])
    (work / "README.md").write_text("hi\n")
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

    async def test_rejects_unreachable_remote(self):
        with self.assertRaises(InvalidRepoURI):
            await WorkspaceService().validate_uri("file:///nope/does-not-exist.git")


class TestSetupCallDir(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.uri = _init_bare_remote(self.tmp)
        self.workspaces = self.tmp / "workspaces"
        self.workspaces.mkdir()
        self.svc = WorkspaceService(base_path=self.workspaces)

    async def asyncTearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    async def test_first_call_clones_default_branch(self):
        sid = uuid4()
        cid = uuid4()
        path = await self.svc.setup_call_dir(
            session_id=sid, call_id=cid, repo_uri=self.uri, branch=None
        )
        self.assertTrue(path.is_dir())
        self.assertTrue((path / ".git").is_dir())
        self.assertTrue((path / "README.md").is_file())
        self.assertEqual(
            path,
            self.workspaces / "sessions" / str(sid) / str(cid),
        )

    async def test_first_call_creates_local_branch(self):
        sid = uuid4()
        cid = uuid4()
        path = await self.svc.setup_call_dir(
            session_id=sid,
            call_id=cid,
            repo_uri=self.uri,
            branch="Nebula/feat-x",
            create_branch=True,
        )
        current = (
            subprocess.check_output(
                ["git", "-C", str(path), "branch", "--show-current"]
            )
            .decode()
            .strip()
        )
        self.assertEqual(current, "Nebula/feat-x")

    async def test_iteration_call_clones_existing_branch(self):
        sid = uuid4()
        cid_first = uuid4()
        first = await self.svc.setup_call_dir(
            session_id=sid,
            call_id=cid_first,
            repo_uri=self.uri,
            branch="Nebula/iter-x",
            create_branch=True,
        )
        subprocess.check_call(
            ["git", "-C", str(first), "push", "origin", "Nebula/iter-x"]
        )
        cid_second = uuid4()
        second = await self.svc.setup_call_dir(
            session_id=sid,
            call_id=cid_second,
            repo_uri=self.uri,
            branch="Nebula/iter-x",
            create_branch=False,
        )
        current = (
            subprocess.check_output(
                ["git", "-C", str(second), "branch", "--show-current"]
            )
            .decode()
            .strip()
        )
        self.assertEqual(current, "Nebula/iter-x")


class TestPushAndCleanup(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.uri = _init_bare_remote(self.tmp)
        self.workspaces = self.tmp / "workspaces"
        self.workspaces.mkdir()
        self.svc = WorkspaceService(base_path=self.workspaces)

    async def asyncTearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    async def test_push_then_cleanup_removes_dir(self):
        sid = uuid4()
        cid = uuid4()
        path = await self.svc.setup_call_dir(
            session_id=sid,
            call_id=cid,
            repo_uri=self.uri,
            branch="Nebula/push-test",
            create_branch=True,
        )
        (path / "new.txt").write_text("x")
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
                "x",
            ]
        )
        await self.svc.push_and_cleanup(call_dir=path, branch="Nebula/push-test")
        self.assertFalse(path.exists())
        out = subprocess.check_output(
            ["git", "ls-remote", "--heads", self.uri, "Nebula/push-test"]
        ).decode()
        self.assertIn("Nebula/push-test", out)

    async def test_cleanup_removes_dir(self):
        sid = uuid4()
        cid = uuid4()
        path = await self.svc.setup_call_dir(
            session_id=sid,
            call_id=cid,
            repo_uri=self.uri,
            branch=None,
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
        """Fake call dir with an iac subdir holding the plan artifact."""
        clone = self.tmp / str(self.sid) / str(uuid4())
        (clone / "iac").mkdir(parents=True)
        (clone / "iac" / SESSION_PLAN_FILENAME).write_text(marker)
        return clone

    def test_pin_renames_clone_into_pinned_slot(self):
        clone = self._make_clone()

        self.svc.pin_workspace(self.sid, clone)

        self.assertFalse(clone.exists())
        pinned = self.svc.pinned_dir(self.sid)
        self.assertEqual(pinned, self.tmp / str(self.sid) / "pinned")
        self.assertTrue((pinned / "iac" / SESSION_PLAN_FILENAME).is_file())

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
