# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""/iac endpoints: validate, resolve the session and queue the operation.

No workers run here (no lifespan), so every accepted call leaves exactly
one PENDING operation row behind for the assertions.
"""

import unittest
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

from httpx import ASGITransport, AsyncClient

from src.api.deps import get_current_user
from src.domains.services.database_service import DatabaseService
from src.domains.services.user_service import UserService
from src.domains.value_objects import TokenClaims
from src.infrastructure.database.database import db
from src.infrastructure.database.models import Base, Operation
from src.infrastructure.exceptions import RepositoryUnreachable
from src.infrastructure.redis import redis_client
from src.main import app
from src.shared.constants import (
    OperationRole,
    OperationStatus,
    OperationType,
    TerraformProvider,
)

_FIRST_CALL = {
    "repo_uri": "https://github.example.com/org/iac.git",
    "terraform_providers": "azure",
    "scope_id": "dev",
    "iac_path": "infra",
}


class _IacApiBase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await db.initialize()
        await redis_client.initialize()
        async with db.session_manager.engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        # The dev identity is elevated (devops), so every route is allowed.
        self.user = await UserService.resolve()
        app.dependency_overrides[get_current_user] = lambda: self.user
        self.client = AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        )
        self._uri_patch = patch(
            "src.api.v1.terraform._workspace.validate_uri", AsyncMock()
        )
        self.validate_uri = self._uri_patch.start()

    async def asyncTearDown(self):
        self._uri_patch.stop()
        app.dependency_overrides.clear()
        await self.client.aclose()
        await redis_client.close()
        await db.close()

    async def _seed_session(self) -> UUID:
        sid = uuid4()
        _ = await DatabaseService.create_session(
            session_id=sid,
            user_pk=self.user.id,
            operation=OperationType.GENERATE,
            repo_uri="https://github.example.com/org/iac.git",
            terraform_prv=TerraformProvider.AZURE,
            scope_id="dev",
            branch_name="Kumoss/x",
            query="seed",
            iac_path="",
        )
        return sid

    async def _operations(self) -> list[Operation]:
        return await db.list_by(Operation, order_by="id", order_desc=False)


class TestGenerateEndpoint(_IacApiBase):
    async def test_first_call_queues_a_generate_operation(self):
        resp = await self.client.post(
            "/v1/iac/generate", json={**_FIRST_CALL, "q": "hello"}
        )
        self.assertEqual(resp.status_code, 202, resp.text)
        body = resp.json()
        [op] = await self._operations()
        self.assertEqual(body["operation_id"], str(op.uuid))
        self.assertEqual(body["session_id"], str(op.session.uuid))
        self.assertEqual(op.kind, OperationType.GENERATE)
        self.assertEqual(op.status, OperationStatus.PENDING)
        self.assertEqual(op.params["q"], "hello")

    async def test_first_call_with_unreachable_uri_returns_400(self):
        self.validate_uri.side_effect = RepositoryUnreachable(400)
        resp = await self.client.post(
            "/v1/iac/generate", json={**_FIRST_CALL, "q": "hello"}
        )
        self.assertEqual(resp.status_code, 400, resp.text)
        self.assertEqual(
            resp.json()["detail"],
            "Repository is not reachable or access was denied.",
        )
        self.assertEqual(await self._operations(), [])

    async def test_first_call_with_non_https_uri_returns_422(self):
        for uri in ("git@github.com:org/iac.git", "file:///does/not/exist.git"):
            with self.subTest(uri=uri):
                resp = await self.client.post(
                    "/v1/iac/generate",
                    json={**_FIRST_CALL, "repo_uri": uri, "q": "hello"},
                )
                self.assertEqual(resp.status_code, 422, resp.text)

    async def test_request_with_neither_uri_nor_session_id_returns_422(self):
        resp = await self.client.post("/v1/iac/generate", json={"q": "x"})
        self.assertEqual(resp.status_code, 422, resp.text)


class TestDriftEndpoint(_IacApiBase):
    async def test_drift_first_call_queues_a_drift_operation(self):
        resp = await self.client.post(
            "/v1/iac/drift",
            json={**_FIRST_CALL, "q": "check drift", "is_partial": True},
        )
        self.assertEqual(resp.status_code, 202, resp.text)
        [op] = await self._operations()
        self.assertEqual(op.kind, OperationType.DRIFT)
        self.assertTrue(op.params["is_partial"])

    async def test_drift_requires_devops(self):
        developer = await UserService.resolve(
            TokenClaims(
                issuer="urn:test", subject="dev", email="d@example.com", name=None
            )
        )
        developer = await UserService.set_roles(
            developer.id, operation_role=OperationRole.DEVELOPER, panel_role=None
        )
        app.dependency_overrides[get_current_user] = lambda: developer
        resp = await self.client.post(
            "/v1/iac/drift", json={**_FIRST_CALL, "q": "check drift"}
        )
        self.assertEqual(resp.status_code, 403, resp.text)


class TestApplyEndpoint(_IacApiBase):
    async def test_apply_iteration_call_queues_an_apply_operation(self):
        sid = await self._seed_session()
        resp = await self.client.post("/v1/iac/apply", json={"session_id": str(sid)})
        self.assertEqual(resp.status_code, 202, resp.text)
        [op] = await self._operations()
        self.assertEqual(op.kind, OperationType.APPLY)
        self.assertEqual(op.session.uuid, sid)

    async def test_apply_on_a_blocked_session_returns_409(self):
        sid = await self._seed_session()
        self.assertTrue(await DatabaseService.set_lock(sid, True))
        resp = await self.client.post("/v1/iac/apply", json={"session_id": str(sid)})
        self.assertEqual(resp.status_code, 409, resp.text)
        self.assertEqual(
            resp.json()["detail"],
            f"Session {sid} is blocked; apply is not allowed.",
        )
        self.assertEqual(await self._operations(), [])


class TestActiveOperationConflict(_IacApiBase):
    async def test_second_call_on_a_session_with_an_active_operation_returns_409(self):
        sid = await self._seed_session()
        first = await self.client.post(
            "/v1/iac/generate", json={"session_id": str(sid), "q": "iter 1"}
        )
        self.assertEqual(first.status_code, 202, first.text)
        second = await self.client.post(
            "/v1/iac/generate", json={"session_id": str(sid), "q": "iter 2"}
        )
        self.assertEqual(second.status_code, 409, second.text)
        self.assertEqual(len(await self._operations()), 1)

    async def test_iteration_on_another_users_session_returns_403(self):
        sid = await self._seed_session()
        stranger = await UserService.resolve(
            TokenClaims(
                issuer="urn:test", subject="x", email="x@example.com", name=None
            )
        )
        app.dependency_overrides[get_current_user] = lambda: stranger
        resp = await self.client.post(
            "/v1/iac/generate", json={"session_id": str(sid), "q": "iter"}
        )
        self.assertEqual(resp.status_code, 403, resp.text)


class TestUploadEndpointGone(_IacApiBase):
    async def test_upload_returns_404(self):
        resp = await self.client.post(
            "/v1/upload/project", json={"project": "x", "cloud": "azure"}
        )
        self.assertEqual(resp.status_code, 404)
