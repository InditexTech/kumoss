# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Minimal async Redis client for caching and session state."""

import json
from typing import Any, cast
from datetime import timedelta

from redis.asyncio import Redis

from src.infrastructure.redis.connection import (
    RedisConnectionManager,
    redis_connection,
)
from src.shared.logger import logging

Expiry = int | timedelta


class RedisClient:
    """Async Redis client with JSON helpers for caching / session state."""

    def __init__(self):
        self.connection: RedisConnectionManager = redis_connection
        self._initialized: bool = False

    async def initialize(self) -> None:
        """Initialize the Redis client."""
        if self._initialized:
            logging.warning("Redis client already initialized")
            return

        await self.connection.initialize()

        self._initialized = True
        logging.info("Redis client initialized")

    async def close(self) -> None:
        """Close the Redis client and cleanup resources."""
        await self.connection.close()
        self._initialized = False
        logging.info("Redis client closed")

    @property
    def client(self) -> Redis:
        """Get the underlying Redis client for commands not wrapped here."""
        return self.connection.client

    # --- String values ---------------------------------------------------

    async def get(self, key: str) -> str | None:
        """Get the string value at ``key`` (``None`` if absent)."""
        # decode_responses=True guarantees str, but the stubs stay bytes|str.
        return cast("str | None", await self.client.get(key))

    async def set(
        self,
        key: str,
        value: str | int | float | bytes,
        ttl: Expiry | None = None,
    ) -> None:
        """Set ``key`` to ``value`` with an optional expiry (seconds/timedelta)."""
        _ = await self.client.set(key, value, ex=ttl)

    # --- JSON values (caching / session state) ---------------------------

    async def get_json(self, key: str) -> Any | None:
        """Get and JSON-decode the value at ``key`` (``None`` if absent)."""
        raw = await self.client.get(key)
        return json.loads(raw) if raw is not None else None

    async def set_json(
        self,
        key: str,
        value: Any,
        ttl: Expiry | None = None,
    ) -> None:
        """JSON-encode ``value`` and store it at ``key`` with optional expiry."""
        _ = await self.client.set(key, json.dumps(value, default=str), ex=ttl)

    # --- Key operations --------------------------------------------------

    async def delete(self, *keys: str) -> int:
        """Delete one or more keys, returning the number removed."""
        return await self.client.delete(*keys)

    async def exists(self, *keys: str) -> int:
        """Return how many of the given keys exist."""
        return await self.client.exists(*keys)

    async def expire(self, key: str, ttl: Expiry) -> bool:
        """Set a key's time-to-live (seconds/timedelta)."""
        return await self.client.expire(key, ttl)

    async def ttl(self, key: str) -> int:
        """Return the remaining TTL in seconds (-2 missing, -1 no expiry)."""
        return await self.client.ttl(key)


redis_client = RedisClient()
