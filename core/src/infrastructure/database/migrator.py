# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Bring the database schema to the latest Alembic revision.

Runs at core startup, in one transaction (PostgreSQL DDL is transactional,
so a failed migration leaves the schema untouched) and under an advisory
lock, so two cores starting together never migrate at once.

Databases created before Alembic (by ``create_all``, with no
``alembic_version`` table) are adopted: the idempotent catch-up steps that
used to run at every startup bring them to the baseline, which is then
recorded, and the later revisions apply as usual. One that predates
authentication is too far from the baseline and is refused.
"""

from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from sqlalchemy import JSON, Column, inspect, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine

from src.shared.logger import logging

BASELINE = "0001"

# Arbitrary, but fixed: every core takes the same lock.
_LOCK_KEY = 0x6B756D6F_7373  # "kumoss"

# What a pre-Alembic database may still need to match the baseline.
# Providers used to be a native enum of the platform's own names, stored by
# member name (AZURE, GCP, K8S...). They are now Terraform provider type
# names in a plain column, and providers without a scope have a null scope.
# Idempotent: every statement is a no-op once applied.
_PRE_ALEMBIC_CATCH_UP: tuple[str, ...] = (
    """
    DO $$
    BEGIN
        IF EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'terraform_providers'
              AND column_name = 'provider'
              AND data_type = 'USER-DEFINED'
        ) THEN
            ALTER TABLE terraform_providers
                ALTER COLUMN provider TYPE VARCHAR(64) USING provider::text;
        END IF;
    END $$;
    """,
    """
    UPDATE terraform_providers SET provider = CASE upper(provider)
        WHEN 'AZURE' THEN 'azurerm'
        WHEN 'GCP' THEN 'google'
        WHEN 'AWS' THEN 'aws'
        WHEN 'OCI' THEN 'oci'
        WHEN 'K8S' THEN 'kubernetes'
        WHEN 'KUBERNETES' THEN 'kubernetes'
        WHEN 'VMWARE' THEN 'vsphere'
    END
    WHERE provider IN (
        'AZURE', 'GCP', 'AWS', 'OCI', 'K8S', 'KUBERNETES', 'VMWARE',
        'azure', 'gcp', 'vmware'
    );
    """,
    "ALTER TABLE terraform_providers ALTER COLUMN scope_id DROP NOT NULL;",
    "DROP TYPE IF EXISTS terraformprovider;",
)


def compare_server_default(
    _context: Any,
    _inspected_column: Any,
    metadata_column: Column[Any],
    inspected_default: str | None,
    _metadata_default: Any,
    rendered_metadata_default: str | None,
) -> bool | None:
    """Compare JSON defaults as text: PostgreSQL has no ``=`` for ``json``,
    which Alembic's own comparison relies on. ``None`` defers to Alembic."""
    if not isinstance(metadata_column.type, JSON):
        return None

    def literal(default: str | None) -> str | None:
        return None if default is None else default.split("::")[0].strip("'")

    return literal(inspected_default) != literal(rendered_metadata_default)


def alembic_config(connection: Connection | None = None) -> Config:
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
    config.attributes["connection"] = connection
    return config


def _upgrade(connection: Connection) -> None:
    config = alembic_config(connection)
    tables = inspect(connection)
    if not tables.has_table("alembic_version") and tables.has_table("sessions"):
        if not tables.has_table("users"):
            raise RuntimeError(
                "The database predates authentication (sessions keyed by"
                + " username, no users table) and cannot be adopted: migrate"
                + " it by hand or recreate it."
            )
        logging.info(f"Adopting a pre-Alembic database at revision {BASELINE}")
        for statement in _PRE_ALEMBIC_CATCH_UP:
            _ = connection.execute(text(statement))
        command.stamp(config, BASELINE)
    command.upgrade(config, "head")


async def migrate(engine: AsyncEngine) -> None:
    # A transaction-level lock: PostgreSQL releases it on commit or rollback,
    # so a failed migration rolls back whole and frees it with no cleanup.
    async with engine.begin() as connection:
        _ = await connection.execute(
            text("SELECT pg_advisory_xact_lock(:key)"), {"key": _LOCK_KEY}
        )
        await connection.run_sync(_upgrade)
