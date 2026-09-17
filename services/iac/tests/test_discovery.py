# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Provider dispatch for scope discovery."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from src.discovery import (
    AwsScopeLister,
    AzureScopeLister,
    GcpScopeLister,
    ScopeDiscovery,
)


def lister_for(terraform_provider: str) -> object | None:
    async def call() -> object | None:
        async with httpx.AsyncClient() as client:
            return ScopeDiscovery({}).lister(terraform_provider, client)

    return asyncio.run(call())


@pytest.mark.parametrize(
    ("terraform_provider", "expected"),
    [
        ("azure", AzureScopeLister),
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
        async with ScopeDiscovery({}).client() as client:
            return client.timeout

    assert asyncio.run(call()).read == 60.0
