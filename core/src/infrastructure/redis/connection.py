# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Redis connection management with a shared async connection pool."""

from redis.asyncio import Redis, ConnectionPool

from src.shared.logger import logging
from src.shared.exceptions import ExceptionHandler
from ._config import redis_config


class RedisConnectionManager:
    """Manages the async Redis client and its connection pool."""

    def __init__(self):
        self._pool: ConnectionPool | None = None
        self._client: Redis | None = None

    async def initialize(self) -> None:
        """Initialize the connection pool and verify connectivity."""
        if self._client is not None:
            logging.warning("Redis connection manager already initialized")
            return

        try:
            self._pool = ConnectionPool.from_url(
                redis_config.redis_url,
                max_connections=10,
                decode_responses=True,
                health_check_interval=30,
            )
            self._client = Redis(connection_pool=self._pool)

            _ = await self._client.ping()

            logging.info("Redis connection manager initialized successfully")

        except Exception as e:
            logging.error(f"Failed to initialize redis connection manager: {e}")
            raise ExceptionHandler(
                message=f"Failed to initialize redis: {str(e)}",
                error_code=500,
            )

    async def close(self) -> None:
        """Close the Redis client and disconnect the pool."""
        if self._client is None:
            return

        await self._client.aclose()
        if self._pool is not None:
            await self._pool.disconnect()
        self._client = None
        self._pool = None
        logging.info("Redis connection manager closed")

    @property
    def client(self) -> Redis:
        """Get the Redis client."""
        if self._client is None:
            raise ExceptionHandler(
                message="Redis connection manager not initialized",
                error_code=500,
            )
        return self._client


redis_connection = RedisConnectionManager()
