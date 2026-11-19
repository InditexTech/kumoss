# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import unittest
from pathlib import Path
from typing import override

from src.domains.exceptions import ObjectNotFound, ObjectStorageError
from src.domains.interfaces import IObjectStorage
from src.domains.value_objects import RootModuleRef
from src.infrastructure.storage.manifest_secret_store import (
    ObjectStorageManifestSecretStore,
    normalize_repo_uri,
    secrets_key,
)


class MemoryStorage(IObjectStorage):
    def __init__(self):
        self.objects: dict[str, bytes] = {}

    @override
    async def ensure_bucket(self) -> None:
        pass

    @override
    async def put(
        self, key: str, data: bytes, content_type: str, metadata: dict[str, str]
    ) -> None:
        self.objects[key] = data

    @property
    @override
    def metadata_header_prefix(self) -> str:
        return ""

    @override
    async def get(self, key: str) -> bytes:
        if key not in self.objects:
            raise ObjectNotFound("missing", 404)
        return self.objects[key]

    @override
    async def exists(self, key: str) -> bool:
        return key in self.objects

    @override
    async def delete(self, key: str) -> None:
        _ = self.objects.pop(key, None)

    @override
    def presigned_get_url(self, key: str, expires_in: int | None = None) -> str:
        return key


MODULE = RootModuleRef("https://github.com/org/repo", "infra/dev", Path("/w/1"))


class TestManifestSecretStore(unittest.IsolatedAsyncioTestCase):
    @override
    def setUp(self):
        self.storage = MemoryStorage()
        self.store = ObjectStorageManifestSecretStore(self.storage)

    async def test_round_trip_and_removal(self):
        self.assertEqual(await self.store.load(MODULE), {})
        await self.store.save(MODULE, {"pw": "x", "obj": {"a": [1]}})
        self.assertEqual(await self.store.load(MODULE), {"pw": "x", "obj": {"a": [1]}})
        await self.store.save(MODULE, {})
        self.assertEqual(self.storage.objects, {})

    async def test_shared_across_clones_and_spellings(self):
        await self.store.save(MODULE, {"pw": "x"})
        other_clone = RootModuleRef(
            "https://bot@GitHub.com/Org/Repo.git/", "./infra/dev/", Path("/w/2")
        )
        self.assertEqual(await self.store.load(other_clone), {"pw": "x"})

    async def test_corrupt_object_is_an_error(self):
        self.storage.objects[secrets_key(MODULE)] = b"not json"
        with self.assertRaises(ObjectStorageError):
            _ = await self.store.load(MODULE)

    def test_key_hides_identity_and_separates_modules(self):
        key = secrets_key(MODULE)
        self.assertRegex(key, r"^manifests/[0-9a-f]{64}/secrets\.json$")
        self.assertNotIn("github", key)
        self.assertNotEqual(
            key, secrets_key(RootModuleRef(MODULE.repo_uri, "infra/pro", Path("/w")))
        )

    def test_normalize_repo_uri(self):
        for uri in (
            "https://github.com/org/repo",
            "https://user:token@github.com/org/repo.git",
            "HTTPS://GITHUB.COM:443/Org/Repo/",
            "git@github.com:org/repo.git",
            "ssh://git@github.com/org/repo",
        ):
            with self.subTest(uri):
                self.assertEqual(normalize_repo_uri(uri), "github.com/org/repo")
        self.assertEqual(
            normalize_repo_uri("https://git.corp:8443/x/y"), "git.corp:8443/x/y"
        )
