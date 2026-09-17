# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Shared pieces of the per-cloud scope listers."""

from __future__ import annotations

from typing import Any, ClassVar, Protocol, cast

import httpx


class DiscoveryError(Exception):
    """A scope listing could not be completed."""


class ScopeLister(Protocol):
    """One cloud's answer to what exists under a scope."""

    async def list_resource_ids(self, scope_id: str) -> list[str]: ...


def as_mapping(value: Any) -> dict[str, Any]:
    """The value as a JSON object, or an empty one."""
    if isinstance(value, dict):
        return cast("dict[str, Any]", value)
    return {}


def as_list(value: Any) -> list[Any]:
    """The value as a JSON array, or an empty one."""
    if isinstance(value, list):
        return cast("list[Any]", value)
    return []


def as_text(value: Any) -> str:
    """The value as a string, or empty when it is anything else."""
    return value if isinstance(value, str) else ""


def require_mapping(value: Any, source: str) -> dict[str, Any]:
    """The value as a JSON object, or a DiscoveryError naming the source."""
    if not isinstance(value, dict):
        raise DiscoveryError(f"{source} returned a body that is not a JSON object")
    return cast("dict[str, Any]", value)


class CloudApi:
    """JSON calls against one cloud REST API, with its errors mapped."""

    _MESSAGE_LIMIT: ClassVar[int] = 1000

    def __init__(self, client: httpx.AsyncClient, source: str, token: str) -> None:
        self._client: httpx.AsyncClient = client
        self._source: str = source
        self._token: str = token

    async def get(
        self, url: str, params: dict[str, str] | None = None
    ) -> dict[str, Any]:
        return await self._send("GET", url, params, None)

    async def post(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._send("POST", url, None, payload)

    async def _send(
        self,
        method: str,
        url: str,
        params: dict[str, str] | None,
        payload: dict[str, Any] | None,
    ) -> dict[str, Any]:
        try:
            response = await self._client.request(
                method,
                url,
                params=params,
                json=payload,
                headers={"Authorization": f"Bearer {self._token}"},
            )
        except httpx.HTTPError as exc:
            raise DiscoveryError(f"{self._source} is unreachable: {exc}") from exc
        except (httpx.InvalidURL, UnicodeEncodeError) as exc:
            raise DiscoveryError(
                f"{self._source} was given an unusable URL: {exc}"
            ) from exc
        if response.status_code >= httpx.codes.BAD_REQUEST:
            raise DiscoveryError(
                f"{response.status_code} from {self._source}: {self._message(response)}"
            )
        return require_mapping(self._json(response), self._source)

    def _message(self, response: httpx.Response) -> str:
        error = as_mapping(as_mapping(self._json(response)).get("error"))
        message = as_text(error.get("message"))
        if message:
            return message[: self._MESSAGE_LIMIT]
        return response.text[: self._MESSAGE_LIMIT] or "(no message)"

    def _json(self, response: httpx.Response) -> Any:
        try:
            return response.json()
        except ValueError:
            return None
