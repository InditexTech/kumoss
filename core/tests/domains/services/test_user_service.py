# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import asyncio
import unittest
from unittest.mock import patch
from uuid import uuid4

from src.domains.exceptions import UserNotFound
from src.domains.services.user_service import DEV_CLAIMS, UserService
from src.domains.value_objects import TokenClaims
from src.infrastructure.database.database import db
from src.infrastructure.database.models import Base
from src.shared.config.system_config import system_config
from src.shared.constants import OperationRole, PanelRole


def _claims(**overrides) -> TokenClaims:
    payload = {
        "issuer": "https://idp.test",
        "subject": f"sub-{uuid4().hex[:8]}",
        "email": "alice@example.com",
        "name": "Alice",
        "email_verified": True,
    }
    payload.update(overrides)
    return TokenClaims(**payload)


class TestUserService(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await db.initialize()
        async with db.session_manager.engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)

    async def asyncTearDown(self):
        await db.close()

    async def test_first_login_provisions_developer_without_panel_access(self):
        user = await UserService.resolve(_claims())
        self.assertIs(user.operation_role, OperationRole.DEVELOPER)
        self.assertIsNone(user.panel_role)
        self.assertEqual(user.email, "alice@example.com")
        self.assertEqual(user.display_name, "Alice")

    async def test_second_login_reuses_the_row(self):
        claims = _claims()
        first = await UserService.resolve(claims)
        second = await UserService.resolve(claims)
        self.assertEqual(first.id, second.id)

    async def test_profile_syncs_on_login(self):
        claims = _claims()
        user = await UserService.resolve(claims)
        updated = await UserService.resolve(
            _claims(
                subject=claims.subject, email="new@example.com", name="Alice Cooper"
            )
        )
        self.assertEqual(updated.id, user.id)
        self.assertEqual(updated.email, "new@example.com")
        self.assertEqual(updated.display_name, "Alice Cooper")

    async def test_absent_claims_do_not_wipe_profile(self):
        claims = _claims()
        _ = await UserService.resolve(claims)
        updated = await UserService.resolve(
            _claims(subject=claims.subject, email=None, name=None)
        )
        self.assertEqual(updated.email, "alice@example.com")
        self.assertEqual(updated.display_name, "Alice")

    async def test_root_email_provisions_elevated(self):
        with patch.object(
            system_config.admin, "default_root_email", "Root@Example.com"
        ):
            user = await UserService.resolve(_claims(email="root@example.com"))
        self.assertIs(user.operation_role, OperationRole.DEVOPS)
        self.assertIs(user.panel_role, PanelRole.ADMIN)

    async def test_unverified_root_email_is_not_elevated(self):
        with patch.object(
            system_config.admin, "default_root_email", "root@example.com"
        ):
            user = await UserService.resolve(
                _claims(email="root@example.com", email_verified=False)
            )
        self.assertIs(user.operation_role, OperationRole.DEVELOPER)
        self.assertIsNone(user.panel_role)

    async def test_root_email_elevates_an_existing_user(self):
        claims = _claims(email="root@example.com")
        user = await UserService.resolve(claims)
        self.assertIsNone(user.panel_role)
        with patch.object(
            system_config.admin, "default_root_email", "root@example.com"
        ):
            elevated = await UserService.resolve(claims)
        self.assertEqual(elevated.id, user.id)
        self.assertIs(elevated.operation_role, OperationRole.DEVOPS)
        self.assertIs(elevated.panel_role, PanelRole.ADMIN)

    async def test_elevation_is_one_way(self):
        claims = _claims(email="root@example.com")
        with patch.object(
            system_config.admin, "default_root_email", "root@example.com"
        ):
            _ = await UserService.resolve(claims)
        # Config cleared afterwards: the user keeps the elevated roles.
        user = await UserService.resolve(claims)
        self.assertIs(user.operation_role, OperationRole.DEVOPS)
        self.assertIs(user.panel_role, PanelRole.ADMIN)

    async def test_dev_claims_resolve_to_a_fully_elevated_user(self):
        user = await UserService.resolve(DEV_CLAIMS)
        self.assertIs(user.operation_role, OperationRole.DEVOPS)
        self.assertIs(user.panel_role, PanelRole.ADMIN)

    async def test_parallel_first_logins_create_one_row(self):
        claims = _claims()
        first, second = await asyncio.gather(
            UserService.resolve(claims), UserService.resolve(claims)
        )
        self.assertEqual(first.id, second.id)
        users, total = await UserService.list_users()
        self.assertEqual(total, 1)
        self.assertEqual(len(users), 1)

    async def test_set_roles_round_trip(self):
        user = await UserService.resolve(_claims())
        updated = await UserService.set_roles(
            user.id,
            operation_role=OperationRole.DEVOPS,
            panel_role=PanelRole.EDITOR,
        )
        self.assertIs(updated.operation_role, OperationRole.DEVOPS)
        self.assertIs(updated.panel_role, PanelRole.EDITOR)
        cleared = await UserService.set_roles(
            user.id,
            operation_role=OperationRole.DEVELOPER,
            panel_role=None,
        )
        self.assertIsNone(cleared.panel_role)

    async def test_set_roles_unknown_user_raises(self):
        with self.assertRaises(UserNotFound):
            _ = await UserService.set_roles(
                999, operation_role=OperationRole.DEVELOPER, panel_role=None
            )

    async def test_list_users_search_matches_email_and_name(self):
        _ = await UserService.resolve(_claims(email="alice@corp.example"))
        _ = await UserService.resolve(
            _claims(email="bob@corp.example", name="Bob Stone")
        )
        _, total = await UserService.list_users(search="alice")
        self.assertEqual(total, 1)
        _, total = await UserService.list_users(search="stone")
        self.assertEqual(total, 1)
        _, total = await UserService.list_users(search="corp.example")
        self.assertEqual(total, 2)
