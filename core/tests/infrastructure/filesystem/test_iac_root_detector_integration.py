# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Integration test for IacRootDetector.

Exercises the full pipeline — clone → ls-tree → _find_roots — against a
local file:// bare repo so it runs without network access.
"""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from src.infrastructure.filesystem.iac_root_detector import IacRootDetector

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


_GIT = ["git", "-c", "user.email=test@test", "-c", "user.name=test"]


def _init_fixture_repo(tmp: Path) -> str:
    """Create a bare repo with a realistic Terraform file tree.

    Returns the ``file://`` URI for the bare remote.
    """
    bare = tmp / "remote.git"
    subprocess.check_call(["git", "init", "--bare", "-b", "main", str(bare)])

    work = tmp / "work"
    subprocess.check_call(["git", "init", "-b", "main", str(work)])

    # — roots that SHOULD be detected —
    _touch(work, "infra/main.tf")
    _touch(work, "infra/variables.tf")
    _touch(work, "app/deploy/provider.tf")
    _touch(work, "app/deploy/terraform.tfvars")
    _touch(work, "standalone/network.tf")

    # — directories that should be EXCLUDED —
    _touch(work, "infra/modules/vpc/main.tf")
    _touch(work, "examples/basic/main.tf")
    _touch(work, "infra/.terraform/providers/registry.tf")

    # — non-terraform files (noise) —
    _touch(work, "README.md")
    _touch(work, "src/main.py")

    subprocess.check_call([*_GIT, "-C", str(work), "add", "."])
    subprocess.check_call([*_GIT, "-C", str(work), "commit", "-m", "fixture"])
    subprocess.check_call(
        ["git", "-C", str(work), "remote", "add", "origin", str(bare)]
    )
    subprocess.check_call(["git", "-C", str(work), "push", "origin", "main"])

    return f"file://{bare}"


def _touch(root: Path, relpath: str) -> None:
    p = root / relpath
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("")


class TestIacRootDetectorIntegration(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.uri = _init_fixture_repo(self.tmp)

    async def asyncTearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    async def test_detect_roots_end_to_end(self):
        detector = IacRootDetector()
        roots = await detector.detect_roots(self.uri)
        self.assertEqual(roots, ["app/deploy", "infra", "standalone"])

    async def test_bogus_uri_raises(self):
        detector = IacRootDetector()
        with self.assertRaises(Exception):
            await detector.detect_roots("file:///no/such/repo.git")
