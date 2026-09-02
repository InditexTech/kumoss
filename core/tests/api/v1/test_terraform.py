# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from src.api.deps import CurrentUser, get_current_user
from src.main import app
from src.infrastructure.database.database import db
from src.infrastructure.database.models import Base
from src.shared.config import system_config
from src.shared.constants import OperationRole


def _caller() -> CurrentUser:
    return CurrentUser(
        id=1,
        issuer="urn:test",
        subject="sub",
        email="dev@example.com",
        display_name="Dev",
        operation_role=OperationRole.DEVELOPER,
        panel_role=None,
    )


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


class TestGenerateEndpoint(unittest.IsolatedAsyncioTestCase):
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

    def test_first_call_returns_202_and_session_id(self):
        uri = _bare_remote(self.tmp)
        resp = self.client.post(
            "/v1/iac/generate",
            json={
                "repo_uri": uri,
                "terraform_providers": "azure",
                "scope_id": "dev",
                "q": "hello",
            },
        )
        self.assertEqual(resp.status_code, 202, resp.text)
        body = resp.json()
        self.assertIn("session_id", body)

    def test_first_call_with_bad_uri_returns_400(self):
        resp = self.client.post(
            "/v1/iac/generate",
            json={
                "repo_uri": "file:///does/not/exist.git",
                "terraform_providers": "azure",
                "scope_id": "dev",
                "q": "hello",
            },
        )
        self.assertEqual(resp.status_code, 400, resp.text)

    def test_request_with_neither_uri_nor_session_id_returns_422(self):
        app.dependency_overrides[get_current_user] = lambda: _caller()
        try:
            resp = self.client.post("/v1/iac/generate", json={"q": "x"})
        finally:
            app.dependency_overrides.pop(get_current_user, None)
        self.assertEqual(resp.status_code, 422, resp.text)


class TestDriftEndpoint(unittest.IsolatedAsyncioTestCase):
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

    def test_drift_first_call_returns_202(self):
        uri = _bare_remote(self.tmp)
        resp = self.client.post(
            "/v1/iac/drift",
            json={
                "repo_uri": uri,
                "terraform_providers": "azure",
                "scope_id": "dev",
                "q": "check drift",
                "is_partial": True,
            },
        )
        self.assertEqual(resp.status_code, 202, resp.text)


class TestApplyEndpoint(unittest.IsolatedAsyncioTestCase):
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
        # Hand the engine back: async connections are bound to the loop
        # that created them, and the seeding coroutine and the TestClient
        # lifespan each run their own loop.
        await db.close()

    async def asyncTearDown(self):
        self._patch.stop()
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_apply_iteration_call_returns_202(self):
        import asyncio
        from uuid import uuid4
        from src.domains.services.database_service import DatabaseService
        from src.domains.services.user_service import DEV_CLAIMS, UserService
        from src.infrastructure.redis import redis_client
        from src.shared.constants import OperationType, TerraformProvider

        sid = uuid4()

        async def seed():
            await db.initialize()
            await redis_client.initialize()
            try:
                # The request runs as the dev identity (auth disabled in
                # test config), so the session must belong to it.
                user = await UserService.resolve(DEV_CLAIMS)
                await DatabaseService.create_session(
                    session_id=sid,
                    user_pk=user.id,
                    operation=OperationType.GENERATE,
                    repo_uri=_bare_remote(self.tmp),
                    terraform_prv=TerraformProvider.AZURE,
                    scope_id="dev",
                    branch_name="Nebula/apply-x",
                    query="seed",
                    iac_path="",
                )
            finally:
                await redis_client.close()
                await db.close()

        asyncio.run(seed())
        # Apply will return 202 even though the branch doesn't yet exist on
        # origin -- the iteration clone will fail in the background. That's
        # acceptable: the endpoint contract is purely the synchronous shape.
        with TestClient(app) as client:
            resp = client.post(
                "/v1/iac/apply",
                json={"session_id": str(sid)},
            )
        self.assertEqual(resp.status_code, 202, resp.text)


class TestInFlightConflict(unittest.IsolatedAsyncioTestCase):
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
        # Hand the engine back: async connections are bound to the loop
        # that created them, and the seeding coroutine and the TestClient
        # lifespan each run their own loop.
        await db.close()

    async def asyncTearDown(self):
        self._patch.stop()
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_second_call_on_active_session_returns_409(self):
        from uuid import uuid4
        from src.domains.services.database_service import DatabaseService
        from src.domains.services.user_service import DEV_CLAIMS, UserService
        from src.infrastructure.redis import redis_client
        from src.shared.constants import OperationType, TerraformProvider
        import asyncio

        sid = uuid4()

        async def seed():
            await db.initialize()
            await redis_client.initialize()
            try:
                user = await UserService.resolve(DEV_CLAIMS)
                await DatabaseService.create_session(
                    session_id=sid,
                    user_pk=user.id,
                    operation=OperationType.GENERATE,
                    repo_uri=_bare_remote(self.tmp),
                    terraform_prv=TerraformProvider.AZURE,
                    scope_id="dev",
                    branch_name="Nebula/x",
                    query="seed",
                    iac_path="",
                )
                await DatabaseService.acquire_in_flight(str(sid))
            finally:
                await redis_client.close()
                await db.close()

        asyncio.run(seed())

        with TestClient(app) as client:
            resp = client.post(
                "/v1/iac/generate",
                json={"session_id": str(sid), "q": "iter"},
            )
        self.assertEqual(resp.status_code, 409, resp.text)


class TestUploadEndpointGone(unittest.TestCase):
    def test_upload_returns_404(self):
        client = TestClient(app)
        resp = client.post(
            "/v1/upload/project", json={"project": "x", "cloud": "azure"}
        )
        self.assertEqual(resp.status_code, 404)
