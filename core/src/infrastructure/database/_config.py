# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Database configuration from environment variables."""

from pydantic_settings import BaseSettings

from pydantic import computed_field

from src.shared.config.system_config import system_config


class DatabaseConfig(BaseSettings):
    """Database configuration using Phoenix SQL database URL."""

    @computed_field
    @property
    def database_url(self) -> str:
        """Get PostgreSQL connection URL from environment."""
        url = system_config.database.kumoss_database_url

        if not url:
            raise ValueError(
                "KUMOSS_SQL_DATABASE_URL environment variable is not set. "
                + "Please set it to connect to PostgreSQL."
            )

        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        url = url.replace("sslmode=", "ssl=")

        return url


db_config = DatabaseConfig()
