# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Behavioral tests for the caching contract of ``RedisClient``.

Runs against a real Redis (the docker-compose service): the properties
under test — SET NX read-repair, single-flight, fail-open — are exactly
the ones a mock would fake away.
"""

import asyncio
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from redis.exceptions import ConnectionError as RedisConnectionError

from src.infrastructure.redis import redis_client


class _DownRedis:
    """Stub client whose every command fails like an unreachable server."""

    async def get(self, *args, **kwargs):
        raise RedisConnectionError("redis is down")

    async def set(self, *args, **kwargs):
        raise RedisConnectionError("redis is down")

    async def delete(self, *args, **kwargs):
        raise RedisConnectionError("redis is down")

    def pipeline(self, *args, **kwargs):
        raise RedisConnectionError("redis is down")


class TestRedisClientCaching(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await redis_client.initialize()
        # Unique namespace per run so tests never collide with dev data.
        self.ns = f"test:{uuid4().hex[:8]}"
        self.keys: list[str] = []

    async def asyncTearDown(self):
        if self.keys:
            _ = await redis_client.invalidate(*self.keys)
        await redis_client.close()

    def _key(self, name: str) -> str:
        key = f"{self.ns}:{name}"
        self.keys.append(key)
        return key

    async def test_miss_caches_and_hit_skips_loader(self):
        key = self._key("basic")
        calls = 0

        async def loader():
            nonlocal calls
            calls += 1
            return {"n": 1}

        first = await redis_client.get_or_set(key, 60, loader)
        second = await redis_client.get_or_set(key, 60, loader)
        self.assertEqual(first, {"n": 1})
        self.assertEqual(second, {"n": 1})
        self.assertEqual(calls, 1)
        # The entry must actually expire.
        ttl = await redis_client.connection.client.ttl(key)
        self.assertGreater(ttl, 0)

    async def test_hit_and_miss_return_identical_shapes(self):
        key = self._key("parity")
        stamp = datetime(2026, 7, 24, 12, 0, 0, tzinfo=timezone.utc)

        async def loader():
            return {"at": stamp, "n": 1}

        miss = await redis_client.get_or_set(key, 60, loader)
        hit = await redis_client.get_or_set(key, 60, loader)
        # Non-JSON types are coerced on the miss path too, so callers see
        # the same shape regardless of which path served them.
        self.assertEqual(miss, hit)
        self.assertIsInstance(miss["at"], str)

    async def test_none_is_not_cached(self):
        key = self._key("negative")
        results = iter([None, {"found": True}])

        async def loader():
            return next(results)

        self.assertIsNone(await redis_client.get_or_set(key, 60, loader))
        self.assertEqual(
            await redis_client.get_or_set(key, 60, loader), {"found": True}
        )

    async def test_nx_never_clobbers_a_written_through_value(self):
        key = self._key("nx-race")

        async def racing_loader():
            # Simulates a mutator committing and writing through while this
            # reader's DB load is still in flight.
            await redis_client.set_json(key, {"v": "new"}, ttl=60)
            return {"v": "old"}

        # The racing reader returns its own (older) load once...
        self.assertEqual(
            await redis_client.get_or_set(key, 60, racing_loader), {"v": "old"}
        )

        async def must_not_run():
            self.fail("loader ran on what must be a cache hit")

        # ...but the cache keeps the fresher written-through value.
        self.assertEqual(
            await redis_client.get_or_set(key, 60, must_not_run), {"v": "new"}
        )

    async def test_concurrent_misses_single_flight_the_loader(self):
        key = self._key("single-flight")
        calls = 0

        async def slow_loader():
            nonlocal calls
            calls += 1
            await asyncio.sleep(0.05)
            return {"n": 1}

        results = await asyncio.gather(
            *(redis_client.get_or_set(key, 60, slow_loader) for _ in range(5))
        )
        self.assertEqual(calls, 1)
        self.assertTrue(all(r == {"n": 1} for r in results))

    async def test_corrupt_entry_is_dropped_and_repaired(self):
        key = self._key("corrupt")
        _ = await redis_client.connection.client.set(key, "{not json", ex=60)

        async def loader():
            return {"ok": 1}

        self.assertEqual(await redis_client.get_or_set(key, 60, loader), {"ok": 1})

        async def must_not_run():
            self.fail("corrupt entry was not repaired")

        self.assertEqual(
            await redis_client.get_or_set(key, 60, must_not_run), {"ok": 1}
        )

    async def test_callable_ttl_is_resolved_from_the_loaded_value(self):
        key = self._key("callable-ttl")

        async def loader():
            return {"kind": "long-lived"}

        def pick_ttl(value):
            return 3600 if value["kind"] == "long-lived" else 60

        _ = await redis_client.get_or_set(key, pick_ttl, loader)
        ttl = await redis_client.connection.client.ttl(key)
        self.assertGreater(ttl, 60)

    async def test_get_json_reads_what_set_json_wrote(self):
        key = self._key("get-json")
        self.assertIsNone(await redis_client.get_json(key))
        await redis_client.set_json(key, {"a": 1}, ttl=60)
        self.assertEqual(await redis_client.get_json(key), {"a": 1})

    async def test_set_json_many_writes_all_keys(self):
        keys = [self._key("many-a"), self._key("many-b")]
        await redis_client.set_json_many([(keys[0], 1, 60), (keys[1], {"b": 2}, 60)])

        async def must_not_run():
            self.fail("set_json_many entry missing")

        self.assertEqual(await redis_client.get_or_set(keys[0], 60, must_not_run), 1)
        self.assertEqual(
            await redis_client.get_or_set(keys[1], 60, must_not_run), {"b": 2}
        )

    async def test_fail_open_when_redis_is_down(self):
        key = f"{self.ns}:down"  # not registered: nothing is ever written
        real_connection = redis_client.connection
        redis_client.connection = SimpleNamespace(client=_DownRedis())
        try:
            # Reads degrade to the loader, writes and deletes to no-ops —
            # never an exception.
            value = await redis_client.get_or_set(key, 60, self._loader_42)
            self.assertEqual(value, {"n": 42})
            await redis_client.set_json(key, {"n": 1}, ttl=60)
            await redis_client.set_json_many([(key, {"n": 1}, 60)])
            self.assertEqual(await redis_client.invalidate(key), 0)
        finally:
            redis_client.connection = real_connection

    @staticmethod
    async def _loader_42():
        return {"n": 42}
