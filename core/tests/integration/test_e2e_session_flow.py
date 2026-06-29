# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import asyncio
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, AsyncMock

from fastapi.testclient import TestClient

from src.main import app
from src.domains.dto import PullRequestDTO
from src.domains.services.database_service import DatabaseService
from src.infrastructure.database.database import db
from src.infrastructure.database.models import Base
from src.shared.config import system_config


def _bare_remote(tmp: Path) -> str:
    bare = tmp / "remote.git"
    subprocess.check_call(["git", "init", "--bare", "-b", "main", str(bare)])
    work = tmp / "seed"
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


class TestEndToEndSessionLifecycle(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.workspaces = self.tmp / "workspaces"
        self.workspaces.mkdir()
        self._patch = patch.object(
            system_config.paths, "upload_folder", self.workspaces
        )
        self._patch.start()
        await db.initialize()
        async with db.session_manager.engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        self.client = TestClient(app)

    async def asyncTearDown(self):
        self._patch.stop()
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)
        await db.close()

    def test_first_call_then_pr_marks_session_completed(self):
        uri = _bare_remote(self.tmp)
        # First call (background task may fail in isolated test env due to LLM
        # config; we only verify the synchronous shape and the session row).
        resp = self.client.post(
            "/v1/iac/generate",
            json={
                "repo_uri": uri,
                "cloud": "azure",
                "environment": "dev",
                "user_id": "u@e.com",
                "q": "hi",
            },
        )
        self.assertEqual(resp.status_code, 202, resp.text)
        sid = resp.json()["session_id"]

        # Force in_flight off (background task may still be running).
        asyncio.run(DatabaseService.release_in_flight(sid))

        # PR creation
        with patch(
            "src.api.v1.repository.GitUtils.create_pr",
            new=AsyncMock(return_value=PullRequestDTO(pr_id=1, status="open")),
        ):
            pr_resp = self.client.put(
                "/v1/repository/pr", json={"session_id": sid, "q": "PR title"}
            )
        self.assertEqual(pr_resp.status_code, 201, pr_resp.text)

        row = asyncio.run(DatabaseService.load_session(sid))
        self.assertEqual(row.status, "completed")
