# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Redis configuration from environment variables."""

from pydantic_settings import BaseSettings

from pydantic import computed_field

from src.shared.config.system_config import system_config


class RedisConfig(BaseSettings):
    """Redis configuration using the Nebula Redis URL."""

    @computed_field
    @property
    def redis_url(self) -> str:
        """Get the Redis connection URL (falls back to the compose default)."""
        return system_config.redis.redis_url


redis_config = RedisConfig()
