# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Behavioral tests for ``S3ObjectStorage`` against the real RustFS.

Runs against the docker-compose ``object-storage`` service: signature
compatibility, presigned-URL fetchability and error translation are
exactly the properties a mock would fake away. Both endpoints point at
the in-network address because these tests run inside the compose
network, where the browser-facing host is not resolvable.
"""

import unittest
from uuid import uuid4

import boto3
import httpx
from botocore.client import Config as BotoConfig
from src.domains.exceptions import ObjectNotFound, ObjectStorageUnavailable
from src.infrastructure.storage._s3 import S3ObjectStorage

_ENDPOINT = "http://object-storage:9000"
_ACCESS_KEY = "rustfsadmin"
_SECRET_KEY = "rustfsadmin"
_REGION = "us-east-1"
_EXPIRY = 172_800


class TestS3ObjectStorage(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Unique bucket per test so runs never collide with dev data.
        self.bucket = f"test-{uuid4().hex[:12]}"
        self.storage = S3ObjectStorage(
            bucket=self.bucket,
            region=_REGION,
            endpoint_url=_ENDPOINT,
            public_endpoint_url=_ENDPOINT,
            access_key=_ACCESS_KEY,
            secret_key=_SECRET_KEY,
            presign_expiry_seconds=_EXPIRY,
        )
        await self.storage.ensure_bucket()

    async def asyncTearDown(self):
        # Raw client cleanup: the port deliberately has no bucket delete.
        client = boto3.client(
            "s3",
            endpoint_url=_ENDPOINT,
            region_name=_REGION,
            aws_access_key_id=_ACCESS_KEY,
            aws_secret_access_key=_SECRET_KEY,
            config=BotoConfig(
                signature_version="s3v4", s3={"addressing_style": "path"}
            ),
        )
        try:
            listed = client.list_objects_v2(Bucket=self.bucket)
            for obj in listed.get("Contents", []):
                client.delete_object(Bucket=self.bucket, Key=obj["Key"])
            client.delete_bucket(Bucket=self.bucket)
        except Exception:
            pass  # best-effort: throwaway data in the test store

    async def test_ensure_bucket_is_idempotent(self):
        await self.storage.ensure_bucket()  # second call must not raise

    async def test_put_get_roundtrip(self):
        await self.storage.put("dir/a.txt", b"payload", "text/plain", {})
        self.assertEqual(await self.storage.get("dir/a.txt"), b"payload")

    async def test_exists_true_and_false(self):
        await self.storage.put("here.txt", b"x", "text/plain", {})
        self.assertTrue(await self.storage.exists("here.txt"))
        self.assertFalse(await self.storage.exists("not-here.txt"))

    async def test_delete_is_idempotent(self):
        await self.storage.put("gone.txt", b"x", "text/plain", {})
        await self.storage.delete("gone.txt")
        await self.storage.delete("gone.txt")  # second delete must not raise
        self.assertFalse(await self.storage.exists("gone.txt"))

    async def test_get_missing_raises_object_not_found(self):
        with self.assertRaises(ObjectNotFound):
            _ = await self.storage.get("missing.txt")

    async def test_presigned_get_fetches_via_plain_http(self):
        """The browser path: a raw fetch with no auth headers."""
        await self.storage.put("signed.json", b'{"ok": true}', "application/json", {})
        url = self.storage.presigned_get_url("signed.json")
        async with httpx.AsyncClient() as http:
            response = await http.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b'{"ok": true}')
        self.assertEqual(response.headers.get("content-type"), "application/json")

    async def test_ranged_get_returns_206_with_the_type_metadata(self):
        """The timeline's label path: one byte back, metadata intact.

        ``fetchPlanType`` in the web client reads a plan's flavour without
        downloading it, which only works if a ranged read still carries
        the object's metadata headers.
        """
        key = "sessions/s/rounds/1/plans/drift-abc12345.txt"
        await self.storage.put(key, b"a diff", "text/plain", {"type": "drift"})
        url = self.storage.presigned_get_url(key)

        async with httpx.AsyncClient() as http:
            response = await http.get(url, headers={"Range": "bytes=0-0"})

        self.assertEqual(response.status_code, 206)
        self.assertEqual(response.headers["x-amz-meta-type"], "drift")

    async def test_metadata_key_with_an_underscore_survives_the_round_trip(self):
        """``new_file`` is the one metadata key that is not a bare word.

        Underscores are legal in HTTP header names but routinely stripped
        by proxies, and this one decides whether the viewer renders a diff
        or a whole file. Pin the round trip against a live store.
        """
        key = "sessions/s/rounds/1/code_changes/vars-abc12345.tf"
        await self.storage.put(
            key, b'variable "a" {}', "text/plain", {"new_file": "true"}
        )
        url = self.storage.presigned_get_url(key)

        async with httpx.AsyncClient() as http:
            response = await http.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["x-amz-meta-new_file"], "true")

    async def test_metadata_header_prefix_matches_what_the_store_returns(self):
        """The value served on ``GET /v1/auth/config``.

        Asserted against a real response rather than a literal, so the
        constant cannot drift away from the store's actual behaviour.
        """
        key = "prefix/probe.txt"
        await self.storage.put(key, b"x", "text/plain", {"type": "plan"})

        async with httpx.AsyncClient() as http:
            response = await http.get(self.storage.presigned_get_url(key))

        prefix = self.storage.metadata_header_prefix
        self.assertEqual(prefix, "x-amz-meta-")
        self.assertEqual(response.headers[f"{prefix}type"], "plan")

    async def test_presigned_url_shape(self):
        url = self.storage.presigned_get_url("some/key.txt")
        self.assertTrue(url.startswith(f"{_ENDPOINT}/{self.bucket}/some/key.txt?"))
        self.assertIn("X-Amz-Signature=", url)
        self.assertIn(f"X-Amz-Expires={_EXPIRY}", url)

    async def test_presigned_url_custom_expiry(self):
        url = self.storage.presigned_get_url("some/key.txt", expires_in=600)
        self.assertIn("X-Amz-Expires=600", url)

    async def test_unreachable_endpoint_raises_unavailable(self):
        down = S3ObjectStorage(
            bucket=self.bucket,
            region=_REGION,
            endpoint_url="http://object-storage:9",  # nothing listens here
            public_endpoint_url=None,
            access_key=_ACCESS_KEY,
            secret_key=_SECRET_KEY,
            presign_expiry_seconds=_EXPIRY,
            connect_timeout=0.2,
            read_timeout=0.2,
            max_attempts=1,
        )
        with self.assertRaises(ObjectStorageUnavailable):
            await down.put("x.txt", b"x", "text/plain", {})


if __name__ == "__main__":
    _ = unittest.main()
