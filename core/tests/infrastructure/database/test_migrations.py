# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""The Alembic migrations against a live PostgreSQL.

Tests elsewhere build their schema with ``create_all``. These check that
the migrations build that same schema, so the two never drift apart, and
that a database created before Alembic is adopted with its data intact.
"""

import asyncio
import unittest
from typing import Any

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from src.infrastructure.database._config import db_config
from src.infrastructure.database.migrator import (
    alembic_config,
    compare_server_default,
    migrate,
)
from src.infrastructure.database.models import Base

HEAD = ScriptDirectory.from_config(alembic_config()).get_current_head()


def _schema_drift(connection: Connection) -> list[Any]:
    context = MigrationContext.configure(
        connection,
        opts={
            "compare_type": True,
            "compare_server_default": compare_server_default,
        },
    )
    return compare_metadata(context, Base.metadata)


def _version(connection: Connection) -> str | None:
    return MigrationContext.configure(connection).get_current_revision()


class TestMigrations(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine: AsyncEngine = create_async_engine(db_config.database_url)
        async with self.engine.begin() as conn:
            _ = await conn.execute(text("DROP SCHEMA public CASCADE"))
            _ = await conn.execute(text("CREATE SCHEMA public"))

    async def asyncTearDown(self):
        await self.engine.dispose()

    async def _run(self, fn: Any) -> Any:
        async with self.engine.begin() as conn:
            return await conn.run_sync(fn)

    async def test_migrations_build_the_models_schema(self):
        await migrate(self.engine)

        self.assertEqual(await self._run(_schema_drift), [])
        self.assertEqual(await self._run(_version), HEAD)

    async def test_every_revision_downgrades_and_upgrades_again(self):
        await migrate(self.engine)

        def down_and_up(connection: Connection) -> None:
            config = alembic_config(connection)
            command.downgrade(config, "base")
            command.upgrade(config, "head")

        await self._run(down_and_up)
        self.assertEqual(await self._run(_schema_drift), [])

    async def test_migrating_twice_changes_nothing(self):
        await migrate(self.engine)
        await migrate(self.engine)

        self.assertEqual(await self._run(_version), HEAD)

    async def test_cores_starting_together_migrate_once(self):
        other = create_async_engine(db_config.database_url)
        try:
            await asyncio.gather(migrate(self.engine), migrate(other))
        finally:
            await other.dispose()

        self.assertEqual(await self._run(_schema_drift), [])

    async def test_a_pre_alembic_database_is_adopted(self):
        # The shape create_all and the old startup steps left behind: no
        # alembic_version, no user_queries, providers still a native enum.
        await self._run(Base.metadata.create_all)
        async with self.engine.begin() as conn:
            for statement in (
                "ALTER TABLE histories DROP COLUMN user_queries",
                "CREATE TYPE terraformprovider AS ENUM ('AZURE', 'GCP')",
                "ALTER TABLE terraform_providers ALTER COLUMN provider"
                + " TYPE terraformprovider USING provider::terraformprovider",
                "INSERT INTO users (issuer, subject, operation_role, created_at,"
                + " updated_at) VALUES ('i', 's', 'DEVELOPER', now(), now())",
                "INSERT INTO sessions (uuid, user_id, operation, in_flight,"
                + " is_blocked, created_at, updated_at) SELECT gen_random_uuid(),"
                + " id, 'GENERATE', false, false, now(), now() FROM users",
                "INSERT INTO histories (session_id, first_query, payload,"
                + " chat_payload, created_at, updated_at) SELECT id, 'add a vnet',"
                + " '[]', '[]', now(), now() FROM sessions",
                "INSERT INTO terraform_providers (session_id, provider, scope_id,"
                + " created_at, updated_at) SELECT id, 'AZURE', 'sub-1', now(),"
                + " now() FROM sessions",
            ):
                _ = await conn.execute(text(statement))

        await migrate(self.engine)

        self.assertEqual(await self._run(_version), HEAD)
        self.assertEqual(await self._run(_schema_drift), [])
        async with self.engine.connect() as conn:
            history = (
                await conn.execute(
                    text("SELECT first_query, user_queries FROM histories")
                )
            ).one()
            provider = (
                await conn.execute(text("SELECT provider FROM terraform_providers"))
            ).scalar_one()
            old_enum = (
                await conn.execute(
                    text("SELECT 1 FROM pg_type WHERE typname = 'terraformprovider'")
                )
            ).first()
        self.assertEqual(tuple(history), ("add a vnet", []))
        self.assertEqual(provider, "azurerm")
        self.assertIsNone(old_enum)

    async def test_a_database_from_before_authentication_is_refused(self):
        async with self.engine.begin() as conn:
            _ = await conn.execute(
                text("CREATE TABLE sessions (id serial PRIMARY KEY, username text)")
            )

        with self.assertRaisesRegex(RuntimeError, "predates authentication"):
            await migrate(self.engine)
        self.assertIsNone(await self._run(_version))
