# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Per-cloud scope discovery for the import endpoints."""

from __future__ import annotations

from collections.abc import Mapping
from typing import ClassVar

import httpx

from .aws import AwsScopeLister
from .azure import AzureScopeLister
from .base import CloudApi, DiscoveryError, ScopeLister, unique
from .gcp import GcpScopeLister

__all__ = [
    "AwsScopeLister",
    "AzureScopeLister",
    "CloudApi",
    "DiscoveryError",
    "GcpScopeLister",
    "ScopeDiscovery",
    "ScopeLister",
    "unique",
]


class ScopeDiscovery:
    """The lister that serves one `terraform_provider`, if any."""

    _TIMEOUT: ClassVar[float] = 60.0

    def __init__(self, environ: Mapping[str, str]) -> None:
        self._environ: Mapping[str, str] = environ

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=httpx.Timeout(self._TIMEOUT))

    def lister(
        self, terraform_provider: str, client: httpx.AsyncClient
    ) -> ScopeLister | None:
        if terraform_provider == "azure":
            return AzureScopeLister(self._environ, client)
        if terraform_provider == "gcp":
            return GcpScopeLister(self._environ, client)
        if terraform_provider == "aws":
            return AwsScopeLister(self._environ)
        return None
