# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Database configuration from environment variables."""

import os
from pydantic_settings import BaseSettings
from pydantic import computed_field


class DatabaseConfig(BaseSettings):
    """Database configuration using Phoenix SQL database URL."""

    @computed_field
    @property
    def database_url(self) -> str:
        """Get PostgreSQL connection URL from environment."""
        phoenix_url = os.environ.get("PHOENIX_SQL_DATABASE_URL")

        if not phoenix_url:
            raise ValueError(
                "PHOENIX_SQL_DATABASE_URL environment variable is not set. "
                "Please set it to connect to PostgreSQL."
            )

        url = phoenix_url.replace("postgresql://", "postgresql+asyncpg://", 1)
        url = url.replace("sslmode=", "ssl=")

        return url


db_config = DatabaseConfig()
