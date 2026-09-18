# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""JSON coercion helpers and the shared httpx boundary."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

import httpx
import pytest

from src.discovery._base import (
    CloudApi,
    as_list,
    as_mapping,
    as_text,
    require_mapping,
)
from src.exceptions import DiscoveryError

Handler = Callable[[httpx.Request], httpx.Response]


def _post(handler: Handler) -> dict[str, object]:
    async def call() -> dict[str, object]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            api = CloudApi(client, "Test API", "token-1")
            return await api.post("https://api.test/query", {"query": "q"})

    return asyncio.run(call())


def test_as_mapping_replaces_anything_else_with_an_empty_object() -> None:
    assert as_mapping({"a": 1}) == {"a": 1}
    assert as_mapping(["a"]) == {}
    assert as_mapping(None) == {}


def test_as_list_replaces_anything_else_with_an_empty_array() -> None:
    assert as_list([1, 2]) == [1, 2]
    assert as_list({"a": 1}) == []


def test_as_text_replaces_anything_else_with_an_empty_string() -> None:
    assert as_text("x") == "x"
    assert as_text(7) == ""
    assert as_text(None) == ""


def test_require_mapping_rejects_a_non_object() -> None:
    with pytest.raises(DiscoveryError, match="not a JSON object"):
        _ = require_mapping([1], "Test API")


def test_post_returns_the_json_object_and_carries_the_token() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"data": [{"id": "one"}]})

    assert _post(handler) == {"data": [{"id": "one"}]}
    assert seen[0].headers["authorization"] == "Bearer token-1"
    assert seen[0].method == "POST"


def test_get_issues_a_get_with_its_query_parameters() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"assets": []})

    async def call() -> dict[str, object]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            api = CloudApi(client, "Test API", "token-1")
            return await api.get("https://api.test/assets", {"pageToken": "p2"})

    assert asyncio.run(call()) == {"assets": []}
    assert seen[0].method == "GET"
    assert seen[0].url.params["pageToken"] == "p2"
    assert seen[0].headers["authorization"] == "Bearer token-1"


def test_an_http_error_becomes_the_status_plus_the_cloud_message() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": {"message": "not authorized"}})

    with pytest.raises(DiscoveryError, match="403 from Test API: not authorized"):
        _ = _post(handler)


def test_an_http_error_without_a_message_falls_back_to_the_body() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="upstream exploded")

    with pytest.raises(DiscoveryError, match="500 from Test API: upstream exploded"):
        _ = _post(handler)


def test_a_transport_failure_becomes_a_discovery_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host", request=request)

    with pytest.raises(DiscoveryError, match="Test API is unreachable"):
        _ = _post(handler)


def _get(url: str) -> dict[str, object]:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    async def call() -> dict[str, object]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            api = CloudApi(client, "Test API", "token-1")
            return await api.get(url)

    return asyncio.run(call())


@pytest.mark.parametrize(
    "url",
    [
        pytest.param("https://api.test/projects/a\nb", id="non-printable"),
        pytest.param("https://api.test/projects/a\udcc3b", id="unencodable"),
    ],
)
def test_an_unusable_url_becomes_a_discovery_error(url: str) -> None:
    with pytest.raises(DiscoveryError, match="Test API was given an unusable URL"):
        _ = _get(url)


def test_a_non_object_body_becomes_a_discovery_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[1, 2, 3])

    with pytest.raises(DiscoveryError, match="not a JSON object"):
        _ = _post(handler)
