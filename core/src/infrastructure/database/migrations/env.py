# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Alembic environment.

The core passes its own connection in ``config.attributes["connection"]``
when it migrates at startup. The ``alembic`` CLI passes none, so one is
opened from ``KUMOSS_SQL_DATABASE_URL``.
"""

import asyncio

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from src.infrastructure.database.migrator import compare_server_default
from src.infrastructure.database.models import Base

target_metadata = Base.metadata


def _run(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=compare_server_default,
    )
    with context.begin_transaction():
        context.run_migrations()


async def _run_from_url() -> None:
    from src.infrastructure.database._config import db_config

    engine = create_async_engine(db_config.database_url)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(_run)
            await connection.commit()
    finally:
        await engine.dispose()


if context.is_offline_mode():
    raise SystemExit("Offline (--sql) mode is not supported: run against a database.")

connection: Connection | None = context.config.attributes.get("connection")
if connection is None:
    asyncio.run(_run_from_url())
else:
    _run(connection)
