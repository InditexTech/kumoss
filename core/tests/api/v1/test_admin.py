# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Admin panel API tests: cross-user sessions, locks, role management."""

import unittest
from uuid import uuid4

from httpx import ASGITransport, AsyncClient

from src.api.deps import get_current_user
from src.domains.services.database_service import DatabaseService
from src.domains.services.user_service import UserService
from src.domains.value_objects import TokenClaims
from src.infrastructure.database.database import db
from src.infrastructure.database.models import Base
from src.infrastructure.redis import redis_client
from src.main import app
from src.shared.constants import (
    OperationRole,
    OperationType,
    PanelRole,
    TerraformProvider,
)


class TestAdminApi(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await db.initialize()
        await redis_client.initialize()
        async with db.session_manager.engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        self.admin = await UserService.resolve(
            TokenClaims(
                issuer="urn:test",
                subject="admin",
                email="admin@example.com",
                name="Admin",
            )
        )
        self.admin = await UserService.set_roles(
            self.admin.id,
            operation_role=OperationRole.DEVOPS,
            panel_role=PanelRole.ADMIN,
        )
        app.dependency_overrides[get_current_user] = lambda: self.admin
        self.client = AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        )

    async def asyncTearDown(self):
        app.dependency_overrides.clear()
        await self.client.aclose()
        await redis_client.close()
        await db.close()

    async def _seed_session(self, email: str):
        user = await UserService.resolve(
            TokenClaims(
                issuer="urn:test",
                subject=f"sub-{uuid4().hex[:8]}",
                email=email,
                name=None,
            )
        )
        sid = uuid4()
        _ = await DatabaseService.create_session(
            session_id=sid,
            user_pk=user.id,
            operation=OperationType.GENERATE,
            repo_uri="https://example.com/foo.git",
            terraform_prv=TerraformProvider.AZURE,
            scope_id="sub-123",
            branch_name="Nebula/x",
            query="create a resource group",
            iac_path="infra",
        )
        return user, sid

    async def test_admin_sessions_lists_across_users(self):
        _ = await self._seed_session("a@example.com")
        _ = await self._seed_session("b@example.com")
        resp = await self.client.get("/v1/admin/sessions")
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["total"], 2)
        usernames = {item["username"] for item in body["items"]}
        self.assertEqual(usernames, {"a@example.com", "b@example.com"})

    async def test_admin_sessions_filters_by_owner_email(self):
        _ = await self._seed_session("a@example.com")
        _ = await self._seed_session("b@example.com")
        resp = await self.client.get(
            "/v1/admin/sessions", params={"user_email": "a@example"}
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["total"], 1)
        self.assertEqual(body["items"][0]["username"], "a@example.com")

    async def test_admin_sessions_search_matches_session_id(self):
        _, sid = await self._seed_session("a@example.com")
        _ = await self._seed_session("b@example.com")
        resp = await self.client.get(
            "/v1/admin/sessions", params={"search": str(sid)[:8]}
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["total"], 1)
        self.assertEqual(body["items"][0]["uuid"], str(sid))

    async def test_admin_session_detail(self):
        _, sid = await self._seed_session("a@example.com")
        resp = await self.client.get(f"/v1/admin/sessions/{sid}")
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["uuid"], str(sid))

    async def test_toggle_lock_round_trip(self):
        _, sid = await self._seed_session("a@example.com")
        resp = await self.client.patch(
            f"/v1/admin/sessions/{sid}/toggle_lock", json={"locked": True}
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json(), {"uuid": str(sid), "is_blocked": True})
        self.assertTrue(await DatabaseService.is_session_blocked(sid))

        resp = await self.client.patch(
            f"/v1/admin/sessions/{sid}/toggle_lock", json={"locked": False}
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json(), {"uuid": str(sid), "is_blocked": False})
        self.assertFalse(await DatabaseService.is_session_blocked(sid))

    async def test_users_list_carries_roles_and_identity(self):
        _ = await self._seed_session("a@example.com")
        resp = await self.client.get("/v1/admin/users")
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["total"], 2)
        by_email = {u["email"]: u for u in body["items"]}
        self.assertEqual(by_email["admin@example.com"]["panel_role"], "admin")
        self.assertEqual(by_email["a@example.com"]["operation_role"], "developer")
        self.assertIsNone(by_email["a@example.com"]["panel_role"])
        self.assertEqual(by_email["a@example.com"]["issuer"], "urn:test")

    async def test_set_roles_round_trip(self):
        target, _ = await self._seed_session("a@example.com")
        resp = await self.client.put(
            f"/v1/admin/users/{target.id}/roles",
            json={"operation_role": "devops", "panel_role": "editor"},
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["operation_role"], "devops")
        self.assertEqual(body["panel_role"], "editor")

        resp = await self.client.put(
            f"/v1/admin/users/{target.id}/roles",
            json={"operation_role": "developer"},
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertIsNone(resp.json()["panel_role"])

    async def test_set_roles_unknown_user_is_404(self):
        resp = await self.client.put(
            "/v1/admin/users/999/roles",
            json={"operation_role": "developer"},
        )
        self.assertEqual(resp.status_code, 404, resp.text)

    async def test_admin_cannot_drop_their_own_panel_role(self):
        resp = await self.client.put(
            f"/v1/admin/users/{self.admin.id}/roles",
            json={"operation_role": "devops", "panel_role": "editor"},
        )
        self.assertEqual(resp.status_code, 409, resp.text)

    async def test_admin_keeping_their_own_admin_role_is_allowed(self):
        resp = await self.client.put(
            f"/v1/admin/users/{self.admin.id}/roles",
            json={"operation_role": "developer", "panel_role": "admin"},
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["operation_role"], "developer")
