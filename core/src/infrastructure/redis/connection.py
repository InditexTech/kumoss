# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Redis connection management with a shared async connection pool."""

from redis.asyncio import BlockingConnectionPool, Redis
from redis.asyncio.retry import Retry
from redis.backoff import ExponentialBackoff
from redis.exceptions import (
    ConnectionError as RedisConnectionError,
    TimeoutError as RedisTimeoutError,
)

from src.shared.config.system_config import system_config
from src.shared.logger import logging
from src.shared.exceptions import ExceptionHandler


class RedisConnectionManager:
    """Manages the async Redis client and its connection pool."""

    def __init__(self):
        self._pool: BlockingConnectionPool | None = None
        self._client: Redis | None = None

    async def initialize(self) -> None:
        """Initialize the connection pool and verify connectivity."""
        if self._client is not None:
            logging.warning("Redis connection manager already initialized")
            return

        cfg = system_config.redis
        try:
            # BlockingConnectionPool: when the pool is exhausted under a
            # burst, callers wait (up to ``timeout``) for a free connection
            # instead of erroring out like the default pool does.
            self._pool = BlockingConnectionPool.from_url(
                cfg.redis_url,
                max_connections=cfg.max_connections,
                timeout=cfg.pool_timeout,
                decode_responses=True,
                health_check_interval=30,
                socket_connect_timeout=cfg.socket_connect_timeout,
                socket_timeout=cfg.socket_timeout,
                retry=Retry(ExponentialBackoff(cap=0.5, base=0.05), retries=2),
                retry_on_error=[RedisConnectionError, RedisTimeoutError],
                client_name="kumoss-core",
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
