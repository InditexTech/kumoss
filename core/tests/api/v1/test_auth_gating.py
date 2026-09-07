# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Authentication and role-gating contract tests.

Identity is injected through dependency overrides; the 401 cases patch
the dev-mode switch so the bearer requirement is exercised without a
real IdP.
"""

import unittest
from unittest.mock import patch
from uuid import uuid4

from httpx import ASGITransport, AsyncClient

from src.api.deps import CurrentUser, get_current_user
from src.domains.services.database_service import DatabaseService
from src.infrastructure.database.database import db
from src.infrastructure.database.models import Base, User
from src.infrastructure.redis import redis_client
from src.main import app
from src.shared.constants import (
    OperationRole,
    OperationType,
    PanelRole,
    TerraformProvider,
)


def _user(
    pk: int,
    operation_role: OperationRole = OperationRole.DEVELOPER,
    panel_role: PanelRole | None = None,
) -> CurrentUser:
    return CurrentUser(
        id=pk,
        issuer="urn:test",
        subject=f"sub-{pk}",
        email=f"user{pk}@example.com",
        display_name=f"User {pk}",
        operation_role=operation_role,
        panel_role=panel_role,
    )


class _GatingBase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await db.initialize()
        await redis_client.initialize()
        async with db.session_manager.engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        self.client = AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        )

    async def asyncTearDown(self):
        app.dependency_overrides.clear()
        await self.client.aclose()
        await redis_client.close()
        await db.close()

    def _act_as(self, user: CurrentUser) -> None:
        app.dependency_overrides[get_current_user] = lambda: user

    async def _seed_session(self, email: str):
        user = await db.create(
            User, issuer="urn:test", subject=f"sub-{uuid4().hex[:8]}", email=email
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


class TestBearerRequirement(_GatingBase):
    async def test_missing_token_is_401_with_www_authenticate(self):
        with patch("src.api.deps._oidc_enabled", return_value=True):
            resp = await self.client.get("/v1/users/me")
        self.assertEqual(resp.status_code, 401, resp.text)
        self.assertEqual(resp.headers.get("WWW-Authenticate"), "Bearer")

    async def test_token_without_configured_validator_is_401(self):
        with patch("src.api.deps._oidc_enabled", return_value=True):
            resp = await self.client.get(
                "/v1/users/me", headers={"Authorization": "Bearer garbage"}
            )
        self.assertEqual(resp.status_code, 401, resp.text)

    async def test_authorize_requires_a_token(self):
        with patch("src.api.deps._oidc_enabled", return_value=True):
            resp = await self.client.post(
                "/v1/auth/authorize",
                json={"cloud": "azure", "project_name": "p", "environment": "dev"},
            )
        self.assertEqual(resp.status_code, 401, resp.text)

    async def test_docs_stay_open(self):
        with patch("src.api.deps._oidc_enabled", return_value=True):
            resp = await self.client.get("/openapi.json")
        self.assertEqual(resp.status_code, 200)


class TestOperationRoleGates(_GatingBase):
    async def test_developer_cannot_run_drift(self):
        self._act_as(_user(1, operation_role=OperationRole.DEVELOPER))
        resp = await self.client.post(
            "/v1/iac/drift",
            json={
                "repo_uri": "https://example.com/foo.git",
                "terraform_providers": "azure",
                "scope_id": "dev",
                "q": "check drift",
            },
        )
        self.assertEqual(resp.status_code, 403, resp.text)

    async def test_users_me_reflects_the_caller(self):
        self._act_as(
            _user(3, operation_role=OperationRole.DEVOPS, panel_role=PanelRole.VIEWER)
        )
        resp = await self.client.get("/v1/users/me")
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["operation_role"], "devops")
        self.assertEqual(body["panel_role"], "viewer")

    async def test_panel_role_serializes_null_when_absent(self):
        self._act_as(_user(4))
        resp = await self.client.get("/v1/users/me")
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.json()["panel_role"])


class TestPanelRoleGates(_GatingBase):
    async def test_no_panel_role_cannot_open_admin(self):
        self._act_as(_user(1))
        resp = await self.client.get("/v1/admin/sessions")
        self.assertEqual(resp.status_code, 403, resp.text)

    async def test_viewer_can_list_admin_sessions(self):
        self._act_as(_user(1, panel_role=PanelRole.VIEWER))
        resp = await self.client.get("/v1/admin/sessions")
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["total"], 0)

    async def test_viewer_cannot_toggle_lock(self):
        self._act_as(_user(1, panel_role=PanelRole.VIEWER))
        resp = await self.client.patch(
            f"/v1/admin/sessions/{uuid4()}/toggle_lock", json={"locked": True}
        )
        self.assertEqual(resp.status_code, 403, resp.text)

    async def test_editor_cannot_manage_users(self):
        self._act_as(_user(1, panel_role=PanelRole.EDITOR))
        resp = await self.client.get("/v1/admin/users")
        self.assertEqual(resp.status_code, 403, resp.text)

    async def test_editor_toggle_on_unknown_session_is_404(self):
        self._act_as(_user(1, panel_role=PanelRole.EDITOR))
        resp = await self.client.patch(
            f"/v1/admin/sessions/{uuid4()}/toggle_lock", json={"locked": True}
        )
        self.assertEqual(resp.status_code, 404, resp.text)


class TestSessionOwnership(_GatingBase):
    async def test_owner_reads_their_session(self):
        owner, sid = await self._seed_session("owner@example.com")
        self._act_as(_user(owner.id))
        resp = await self.client.get(f"/v1/sessions/{sid}")
        self.assertEqual(resp.status_code, 200, resp.text)

    async def test_stranger_cannot_read_someone_elses_session(self):
        owner, sid = await self._seed_session("owner@example.com")
        self._act_as(_user(owner.id + 1000))
        resp = await self.client.get(f"/v1/sessions/{sid}")
        self.assertEqual(resp.status_code, 403, resp.text)

    async def test_panel_viewer_may_read_any_session(self):
        owner, sid = await self._seed_session("owner@example.com")
        self._act_as(_user(owner.id + 1000, panel_role=PanelRole.VIEWER))
        resp = await self.client.get(f"/v1/sessions/{sid}")
        self.assertEqual(resp.status_code, 200, resp.text)

    async def test_stranger_cannot_subscribe_to_events(self):
        owner, sid = await self._seed_session("owner@example.com")
        self._act_as(_user(owner.id + 1000))
        resp = await self.client.get(f"/v1/events/subscribe/{sid}")
        self.assertEqual(resp.status_code, 403, resp.text)

    async def test_stranger_cannot_apply_even_with_panel_role(self):
        owner, sid = await self._seed_session("owner@example.com")
        self._act_as(_user(owner.id + 1000, panel_role=PanelRole.ADMIN))
        resp = await self.client.post("/v1/iac/apply", json={"session_id": str(sid)})
        self.assertEqual(resp.status_code, 403, resp.text)

    async def test_list_is_scoped_to_the_caller(self):
        owner_a, _ = await self._seed_session("a@example.com")
        _ = await self._seed_session("b@example.com")
        self._act_as(_user(owner_a.id))
        resp = await self.client.get("/v1/sessions")
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["total"], 1)
        self.assertEqual(body["items"][0]["username"], "a@example.com")
