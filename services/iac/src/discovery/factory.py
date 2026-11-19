# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""The entry point into per-cloud scope discovery."""

from __future__ import annotations

from collections.abc import Mapping
from typing import ClassVar

import httpx

from ..identifiers import unique
from ._aws import AwsScopeLister
from ._azure import AzurosCloudapi
from ._base import ScopeLister
from ._gcp import GcpScopeLister


class ScopeDiscovery:
    """What exists under a scope, for the clouds this service can query."""

    _TIMEOUT: ClassVar[float] = 60.0

    def __init__(self, environ: Mapping[str, str]) -> None:
        self._environ: Mapping[str, str] = environ

    async def resource_ids(self, provider: str, scope_id: str) -> list[str] | None:
        """The scope's resource identifiers, or None when no lister serves
        ``provider`` (a Terraform provider type name)."""
        async with self._client() as client:
            lister = self._lister(provider, client)
            if lister is None:
                return None
            return unique(await lister.list_resource_ids(scope_id))

    async def verify_scope(self, provider: str, scope_id: str) -> None:
        """Raise DiscoveryError when the ambient credentials cannot serve
        ``scope_id`` for ``provider``; callers apply it to every pair.

        Only ``aws`` is checked: its account comes from the credentials,
        while ``azurerm``, ``google`` and ``oci`` commands are pointed at
        ``scope_id`` by the variable the engine injects, and any other
        provider names its scope in the code or runs on ambient
        credentials.
        """
        if provider == "aws":
            await AwsScopeLister(self._environ).verify_account(scope_id)

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=httpx.Timeout(self._TIMEOUT))

    def _lister(self, provider: str, client: httpx.AsyncClient) -> ScopeLister | None:
        if provider == "azurerm":
            return AzurosCloudapi(self._environ, client)
        if provider == "google":
            return GcpScopeLister(self._environ, client)
        if provider == "aws":
            return AwsScopeLister(self._environ)
        return None
