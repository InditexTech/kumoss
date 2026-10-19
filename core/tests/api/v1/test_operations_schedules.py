# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""/operations and /schedules: ownership, validation and cancel."""

import unittest
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

from httpx import ASGITransport, AsyncClient

from src.api.deps import get_current_user
from src.domains.services.database_service import DatabaseService
from src.domains.services.operation_queue_service import OperationQueueService
from src.domains.services.user_service import UserService
from src.domains.value_objects import TokenClaims
from src.infrastructure.database.database import db
from src.infrastructure.database.models import Base
from src.infrastructure.redis import redis_client
from src.main import app
from src.shared.config.system_config import system_config
from src.shared.constants import OperationRole, OperationType, TerraformProvider

_PARAMS = {
    "repo_uri": "https://github.example.com/org/iac.git",
    "terraform_providers": "azure",
    "scope_id": "sub-1",
    "iac_path": "infra",
    "q": "detect drift",
}


class _ApiBase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await db.initialize()
        await redis_client.initialize()
        async with db.session_manager.engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        self.owner = await UserService.resolve()  # elevated: devops
        self.stranger = await UserService.resolve(
            TokenClaims(
                issuer="urn:test", subject="s", email="s@example.com", name=None
            )
        )
        self.as_user(self.owner)
        self.client = AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        )
        self._uri_patch = patch(
            "src.api.v1.schedules._workspace.validate_uri", AsyncMock()
        )
        _ = self._uri_patch.start()
        self.queue = OperationQueueService(system_config.scheduler)

    async def asyncTearDown(self):
        self._uri_patch.stop()
        app.dependency_overrides.clear()
        await self.client.aclose()
        await redis_client.close()
        await db.close()

    def as_user(self, user):
        app.dependency_overrides[get_current_user] = lambda: user

    async def _queued_op(self) -> tuple[UUID, UUID]:
        sid = uuid4()
        _ = await DatabaseService.create_session(
            session_id=sid,
            user_pk=self.owner.id,
            operation=OperationType.DRIFT,
            repo_uri=_PARAMS["repo_uri"],
            terraform_prv=TerraformProvider.AZURE,
            scope_id="sub-1",
            branch_name="Kumoss/x",
            query="q",
            iac_path="infra",
        )
        op = await self.queue.enqueue(sid, OperationType.DRIFT, {"q": "q"})
        return sid, op.uuid


class TestOperationsApi(_ApiBase):
    async def test_owner_lists_gets_and_cancels(self):
        sid, op_id = await self._queued_op()

        listed = (await self.client.get("/v1/operations")).json()
        self.assertEqual(listed["total"], 1)
        self.assertEqual(listed["items"][0]["session_uuid"], str(sid))
        self.assertIsNone(listed["items"][0]["schedule_uuid"])

        detail = await self.client.get(f"/v1/operations/{op_id}")
        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertEqual(detail.json()["status"], "pending")

        cancel = await self.client.post(f"/v1/operations/{op_id}/cancel")
        self.assertEqual(cancel.status_code, 202, cancel.text)
        self.assertEqual(cancel.json()["status"], "cancelled")
        again = await self.client.post(f"/v1/operations/{op_id}/cancel")
        self.assertEqual(again.status_code, 409, again.text)

    async def test_strangers_see_nothing_and_cannot_cancel(self):
        sid, op_id = await self._queued_op()
        self.as_user(self.stranger)

        listed = (
            await self.client.get("/v1/operations", params={"session_id": str(sid)})
        ).json()
        self.assertEqual(listed["total"], 0)
        self.assertEqual(
            (await self.client.get(f"/v1/operations/{op_id}")).status_code, 403
        )
        self.assertEqual(
            (await self.client.post(f"/v1/operations/{op_id}/cancel")).status_code, 403
        )

    async def test_unknown_operation_is_404(self):
        resp = await self.client.get(f"/v1/operations/{uuid4()}")
        self.assertEqual(resp.status_code, 404)


class TestSchedulesApi(_ApiBase):
    async def _create(self, **overrides):
        body = {
            "name": "nightly",
            "kind": "drift",
            "cron": "0 3 * * *",
            "params": _PARAMS,
        }
        return await self.client.post("/v1/schedules", json={**body, **overrides})

    async def test_create_belongs_to_the_caller(self):
        resp = await self._create()
        self.assertEqual(resp.status_code, 201, resp.text)
        body = resp.json()
        self.assertEqual(body["owner_email"], self.owner.email)
        self.assertEqual(body["kind"], "drift")
        self.assertFalse(body["params"]["is_partial"])  # normalized
        self.assertIsNotNone(body["next_run_at"])

    async def test_create_validation(self):
        cases = {
            "bad cron": ({"cron": "not a cron"}, 422),
            "unschedulable kind": ({"kind": "generate"}, 422),
            "invalid params": ({"params": {"q": "x"}}, 422),
        }
        for name, (overrides, code) in cases.items():
            with self.subTest(name):
                self.assertEqual((await self._create(**overrides)).status_code, code)

    async def test_drift_schedule_requires_devops(self):
        _ = await UserService.set_roles(
            self.stranger.id, operation_role=OperationRole.DEVELOPER, panel_role=None
        )
        self.as_user(await DatabaseService.get_user(self.stranger.id))
        self.assertEqual((await self._create()).status_code, 403)
        self.assertEqual((await self._create(kind="import")).status_code, 201)

    async def test_strangers_cannot_read_update_or_delete(self):
        schedule_id = (await self._create()).json()["uuid"]
        self.as_user(self.stranger)

        self.assertEqual((await self.client.get("/v1/schedules")).json()["total"], 0)
        self.assertEqual(
            (await self.client.get(f"/v1/schedules/{schedule_id}")).status_code, 403
        )
        patched = await self.client.patch(
            f"/v1/schedules/{schedule_id}", json={"enabled": False}
        )
        self.assertEqual(patched.status_code, 403)
        self.assertEqual(
            (await self.client.delete(f"/v1/schedules/{schedule_id}")).status_code, 403
        )

    async def test_owner_updates_and_deletes(self):
        created = (await self._create()).json()
        schedule_id = created["uuid"]

        patched = await self.client.patch(
            f"/v1/schedules/{schedule_id}",
            json={
                "cron": "*/5 * * * *",
                "enabled": False,
                "params": {**_PARAMS, "q": "new"},
            },
        )
        self.assertEqual(patched.status_code, 200, patched.text)
        body = patched.json()
        self.assertEqual(body["cron"], "*/5 * * * *")
        self.assertFalse(body["enabled"])
        self.assertEqual(body["params"]["q"], "new")
        self.assertNotEqual(body["next_run_at"], created["next_run_at"])

        bad = await self.client.patch(
            f"/v1/schedules/{schedule_id}", json={"cron": "nope"}
        )
        self.assertEqual(bad.status_code, 422)

        deleted = await self.client.delete(f"/v1/schedules/{schedule_id}")
        self.assertEqual(deleted.status_code, 204)
        self.assertEqual(
            (await self.client.get(f"/v1/schedules/{schedule_id}")).status_code, 404
        )
