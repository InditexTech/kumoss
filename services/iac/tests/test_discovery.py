# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Provider dispatch for scope discovery."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import httpx
import pytest

from src.discovery import ScopeDiscovery
from src.discovery._aws import AwsScopeLister
from src.discovery._azure import AzurosCloudapi
from src.discovery._base import ScopeLister
from src.discovery._gcp import GcpScopeLister


class FakeLister:
    """A scope lister with a canned answer, recording what it was asked."""

    def __init__(self, ids: list[str]) -> None:
        self._ids: list[str] = ids
        self.scopes: list[str] = []

    async def list_resource_ids(self, scope_id: str) -> list[str]:
        self.scopes.append(scope_id)
        return self._ids


def lister_for(terraform_provider: str) -> object | None:
    async def call() -> object | None:
        async with httpx.AsyncClient() as client:
            return ScopeDiscovery({})._lister(terraform_provider, client)  # pyright: ignore[reportPrivateUsage]

    return asyncio.run(call())


def resource_ids_for(
    terraform_provider: str, lister: ScopeLister | None
) -> list[str] | None:
    with patch.object(ScopeDiscovery, "_lister", return_value=lister):
        return asyncio.run(ScopeDiscovery({}).resource_ids(terraform_provider, "s-1"))


@pytest.mark.parametrize(
    ("terraform_provider", "expected"),
    [
        ("azure", AzurosCloudapi),
        ("gcp", GcpScopeLister),
        ("aws", AwsScopeLister),
    ],
)
def test_each_supported_provider_gets_its_lister(
    terraform_provider: str, expected: type
) -> None:
    assert isinstance(lister_for(terraform_provider), expected)


@pytest.mark.parametrize("terraform_provider", ["oci", "kubernetes", "", "AZURE"])
def test_other_providers_have_no_lister(terraform_provider: str) -> None:
    assert lister_for(terraform_provider) is None


def test_the_client_carries_the_discovery_timeout() -> None:
    async def call() -> httpx.Timeout:
        async with ScopeDiscovery({})._client() as client:  # pyright: ignore[reportPrivateUsage]
            return client.timeout

    assert asyncio.run(call()).read == 60.0


def test_resource_ids_deduplicates_in_first_seen_order() -> None:
    """The factory owns the dedup, so callers get one identifier per
    resource however many times its cloud names it."""
    lister = FakeLister(["/b", "/a", "/b", "/c", "/a"])

    assert resource_ids_for("azure", lister) == ["/b", "/a", "/c"]
    assert lister.scopes == ["s-1"]


def test_a_provider_without_a_lister_has_no_resource_ids() -> None:
    """None is how the factory says it has no inventory query for the
    provider, which is a different answer from an empty scope."""
    assert resource_ids_for("oci", None) is None
    assert resource_ids_for("azure", FakeLister([])) == []
