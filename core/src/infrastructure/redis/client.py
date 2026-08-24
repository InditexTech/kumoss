# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Minimal async Redis client for caching and session state."""

import asyncio
import json
from typing import Any
from datetime import timedelta
from collections.abc import Awaitable, Callable, Sequence

from redis.asyncio import Redis
from redis.exceptions import RedisError

from src.infrastructure.redis.connection import (
    RedisConnectionManager,
    redis_connection,
)
from src.shared.logger import logging

Expiry = int | timedelta

# The database is the source of truth; Redis being down must never take
# reads down with it. Every cache operation catches these and degrades to
# a miss (reads) or a no-op (writes).
_FAIL_OPEN_ERRORS = (RedisError, OSError)


class RedisClient:
    """Async Redis client with JSON helpers for caching / session state.

    All operations are fail-open: a Redis error is logged and surfaced as
    a cache miss or a skipped write, never as an exception to the caller.
    """

    def __init__(self):
        self.connection: RedisConnectionManager = redis_connection
        self._initialized: bool = False
        # Per-key single-flight registry: key -> [lock, refcount].
        self._loading: dict[str, list[Any]] = {}

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

    # --- Fail-open primitives ---------------------------------------------

    async def _safe_get(self, key: str) -> str | bytes | None:
        try:
            return await self._client.get(key)
        except _FAIL_OPEN_ERRORS as e:
            logging.warning(f"Redis GET {key} failed ({e}); treating as a miss")
            return None

    async def _safe_set(
        self, key: str, encoded: str, ttl: Expiry | None, nx: bool
    ) -> None:
        try:
            _ = await self._client.set(key, encoded, ex=ttl, nx=nx)
        except _FAIL_OPEN_ERRORS as e:
            logging.warning(
                f"Redis SET {key} failed ({e}); "
                + "value not cached, stale reads possible until TTL"
            )

    async def _decode(self, key: str, raw: str | bytes) -> Any | None:
        """JSON-decode a cached entry; a corrupt entry is dropped as a miss."""
        try:
            return json.loads(raw)
        except ValueError:
            logging.warning(f"Corrupt cache entry at {key}; dropping it")
            # Must be deleted: SET NX would otherwise never repair the key.
            _ = await self.invalidate(key)
            return None

    # --- JSON values (caching / session state) ---------------------------

    async def get_json(self, key: str) -> Any | None:
        """Fail-open read of the JSON value at ``key`` (``None`` if absent).

        For conditional caching flows that cannot use ``get_or_set``
        (e.g. only some loaded values are cacheable).
        """
        raw = await self._safe_get(key)
        if raw is None:
            return None
        return await self._decode(key, raw)

    async def set_json(
        self,
        key: str,
        value: Any,
        ttl: Expiry | None = None,
    ) -> None:
        """JSON-encode ``value`` and store it at ``key`` with optional expiry.

        This is the write-through path: it overwrites unconditionally, so
        mutators use it to publish the value they just committed.
        """
        await self._safe_set(key, json.dumps(value, default=str), ttl, nx=False)

    async def set_json_many(
        self, entries: Sequence[tuple[str, Any, Expiry | None]]
    ) -> None:
        """Write-through several ``(key, value, ttl)`` entries in one round trip."""
        try:
            async with self._client.pipeline(transaction=False) as pipe:
                for key, value, ttl in entries:
                    _ = pipe.set(key, json.dumps(value, default=str), ex=ttl)
                _ = await pipe.execute()
        except _FAIL_OPEN_ERRORS as e:
            keys = ", ".join(key for key, _, _ in entries)
            logging.warning(
                f"Redis pipelined SET [{keys}] failed ({e}); "
                "values not cached, stale reads possible until TTL"
            )

    # --- Cache-aside -----------------------------------------------------

    async def get_or_set(
        self,
        key: str,
        ttl: Expiry | Callable[[Any], Expiry | None] | None,
        loader: Callable[[], Awaitable[Any]],
    ) -> Any:
        """Return the JSON value at ``key``, or compute it via ``loader``.

        ``ttl`` may be a callable; it then receives the loaded value and
        returns the expiry, so read-repair can pick a TTL based on what it
        loaded (e.g. long-lived entries for values that can never change).

        Consistency and concurrency properties:

        * misses for the same key are single-flighted per process, so a
          stampede of concurrent readers runs the loader once;
        * the miss path stores with SET NX, so a fresher value written
          through by a mutator between our load and our SET is never
          clobbered with the older loaded value;
        * a ``None`` result is never cached (no negative caching), so
          absent keys keep hitting the source until they exist;
        * hits and misses both return the JSON round-trip of the value,
          so callers see identical shapes on either path.
        """
        raw = await self._safe_get(key)
        if raw is not None:
            value = await self._decode(key, raw)
            if value is not None:
                return value

        entry = self._loading.get(key)
        if entry is None:
            entry = self._loading[key] = [asyncio.Lock(), 0]
        entry[1] += 1
        try:
            async with entry[0]:
                # A concurrent leader may have populated the key while we
                # waited on the lock.
                raw = await self._safe_get(key)
                if raw is not None:
                    value = await self._decode(key, raw)
                    if value is not None:
                        return value

                value = await loader()
                if value is None:
                    return None
                encoded = json.dumps(value, default=str)
                expiry = ttl(value) if callable(ttl) else ttl
                await self._safe_set(key, encoded, expiry, nx=True)
                return json.loads(encoded)
        finally:
            entry[1] -= 1
            if entry[1] == 0:
                _ = self._loading.pop(key, None)

    async def invalidate(self, *keys: str) -> int:
        """Drop cached ``keys`` so the next read recomputes. Returns count removed."""
        try:
            return await self._client.delete(*keys)
        except _FAIL_OPEN_ERRORS as e:
            logging.warning(
                f"Redis DEL {', '.join(keys)} failed ({e}); "
                "stale entries possible until TTL"
            )
            return 0


redis_client = RedisClient()
