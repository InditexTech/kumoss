# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Sensitive variable values of a root module, kept as one object in object storage.

The key derives from the module's identity only (normalized repository
URI and module path), so every clone and branch share it, and is hashed
so neither leaks into object listings.

Object storage is not a secret manager: confidentiality rests on the
bucket's access policy and server-side encryption. ``IManifestSecretStore``
is the seam for moving these values to a vault later.
"""

import hashlib
import json
from collections.abc import Mapping
from typing import final, override
from urllib.parse import urlsplit

from src.domains.exceptions import ObjectNotFound, ObjectStorageError
from src.domains.interfaces.manifest_secret_store_interface import (
    IManifestSecretStore,
)
from src.domains.interfaces.object_storage_interface import IObjectStorage
from src.domains.value_objects.manifest import JsonValue, RootModuleRef

_PREFIX = "manifests"


@final
class ObjectStorageManifestSecretStore(IManifestSecretStore):
    """``IManifestSecretStore`` keeping each module's values as one JSON object."""

    def __init__(self, storage: IObjectStorage):
        self.__storage = storage

    @override
    async def load(self, module: RootModuleRef) -> dict[str, JsonValue]:
        try:
            raw = await self.__storage.get(secrets_key(module))
        except ObjectNotFound:
            return {}
        try:
            values = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise ObjectStorageError(
                "Stored manifest secrets are unreadable.", 500
            ) from e
        if not isinstance(values, dict):
            raise ObjectStorageError("Stored manifest secrets are unreadable.", 500)
        return values

    @override
    async def save(
        self, module: RootModuleRef, values: Mapping[str, JsonValue]
    ) -> None:
        key = secrets_key(module)
        if not values:
            await self.__storage.delete(key)
            return
        await self.__storage.put(
            key,
            json.dumps(dict(values), separators=(",", ":"), sort_keys=True).encode(),
            content_type="application/json",
            metadata={},
        )


def secrets_key(module: RootModuleRef) -> str:
    """Object key of ``module``'s secret values."""
    identity = f"{normalize_repo_uri(module.repo_uri)}\n{module.path}"
    return f"{_PREFIX}/{hashlib.sha256(identity.encode()).hexdigest()}/secrets.json"


def normalize_repo_uri(uri: str) -> str:
    """One spelling per repository: no credentials, case, ``.git`` or trailing slash.

    ``https://user@GitHub.com/Org/Repo.git/`` and ``https://github.com/org/repo``
    name the same repository. An scp-like ``git@host:org/repo`` is read as
    ``ssh://git@host/org/repo``.
    """
    uri = uri.strip()
    if "://" not in uri and ":" in uri:
        uri = "ssh://" + uri.replace(":", "/", 1)
    parts = urlsplit(uri)
    host = (parts.hostname or "").lower()
    if parts.port and parts.port not in (22, 80, 443):
        host = f"{host}:{parts.port}"
    path = parts.path.rstrip("/").removesuffix(".git").rstrip("/").lower()
    return f"{host}{path}"
