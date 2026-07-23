# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Minimal async Redis client for caching and session state."""

import json
from typing import Any
from datetime import timedelta
from collections.abc import Awaitable, Callable

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
    def _client(self) -> Redis:
        """Underlying Redis client for commands not wrapped here."""
        return self.connection.client

    # --- JSON values (caching / session state) ---------------------------

    async def _get_json(self, key: str) -> Any | None:
        """Get and JSON-decode the value at ``key`` (``None`` if absent)."""
        raw = await self._client.get(key)
        return json.loads(raw) if raw is not None else None

    async def set_json(
        self,
        key: str,
        value: Any,
        ttl: Expiry | None = None,
    ) -> None:
        """JSON-encode ``value`` and store it at ``key`` with optional expiry."""
        _ = await self._client.set(key, json.dumps(value, default=str), ex=ttl)

    # --- Cache-aside -----------------------------------------------------

    async def get_or_set(
        self,
        key: str,
        ttl: Expiry | None,
        loader: Callable[[], Awaitable[Any]],
    ) -> Any:
        """Return the JSON value at ``key``, or compute it via ``loader``.

        On a miss the loader runs and its result is cached with ``ttl``.
        A ``None`` result is never cached (no negative caching), so absent
        keys keep hitting the source until they exist.
        """
        cached = await self._get_json(key)
        if cached is not None:
            return cached

        value = await loader()
        if value is not None:
            await self.set_json(key, value, ttl=ttl)
        return value

    async def invalidate(self, *keys: str) -> int:
        """Drop cached ``keys`` so the next read recomputes. Returns count removed."""
        return await self._delete(*keys)

    async def _delete(self, *keys: str) -> int:
        """Delete one or more keys, returning the number removed."""
        return await self._client.delete(*keys)


redis_client = RedisClient()
