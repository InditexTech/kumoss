# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""The slice of Langfuse's public prompt API the core uses.

A thin async client over the REST API rather than the Langfuse SDK: the
SDK's prompt reads are synchronous and cached client-side, while the core
reads prompts from async code and wants a label's current version on
every read; and creating the SDK client also installs its own OTel
pipeline next to the core's.

A label names one version of a prompt at a time: setting it on a version
takes it off any other, and ``latest`` is kept by Langfuse on the newest
version.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx

from src.shared.config import system_config

LATEST = "latest"


@dataclass(frozen=True)
class PromptVersion:
    name: str
    version: int
    labels: tuple[str, ...]
    # The body of a text prompt, or of a chat prompt holding a single
    # message; None for any other shape.
    text: str | None
    # None for a text prompt; for a chat prompt, the role of its first
    # message. A prompt keeps its type across versions: Langfuse refuses a
    # version of the other type.
    chat_role: str | None = None

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> PromptVersion:
        return cls(
            name=data["name"],
            version=data["version"],
            labels=tuple(data.get("labels") or ()),
            text=_text(data),
            chat_role=_chat_role(data),
        )


def _text(data: Mapping[str, Any]) -> str | None:
    prompt = data.get("prompt")
    if data.get("type") == "text":
        return prompt if isinstance(prompt, str) else None
    if not isinstance(prompt, list) or len(prompt) != 1:  # pyright: ignore[reportUnknownArgumentType]
        return None
    message: object = prompt[0]
    content = message.get("content") if isinstance(message, dict) else None
    return content if isinstance(content, str) else None


def _chat_role(data: Mapping[str, Any]) -> str | None:
    if data.get("type") != "chat":
        return None
    prompt = data.get("prompt")
    first: object = prompt[0] if isinstance(prompt, list) and prompt else None
    role = first.get("role") if isinstance(first, dict) else None
    return role if isinstance(role, str) else "user"


class LangfusePrompts:
    def __init__(
        self,
        base_url: str,
        public_key: str,
        secret_key: str,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 10.0,
    ):
        self._client: httpx.AsyncClient = httpx.AsyncClient(
            base_url=f"{base_url.rstrip('/')}/api/public/",
            auth=httpx.BasicAuth(public_key, secret_key),
            timeout=timeout,
            transport=transport,
        )

    async def get(self, name: str, label: str) -> PromptVersion | None:
        """The version ``label`` points at; None when the prompt or the
        label does not exist.

        Raises:
            httpx.HTTPStatusError: any other non-2xx answer.
            httpx.HTTPError: the request did not complete.
        """
        response = await self._client.get(_prompt_path(name), params={"label": label})
        if response.status_code == 404:
            return None
        _ = response.raise_for_status()
        return PromptVersion.from_api(response.json())

    async def create(
        self,
        name: str,
        text: str,
        labels: Sequence[str],
        commit_message: str | None = None,
        chat_role: str | None = None,
    ) -> PromptVersion:
        """A new version of prompt ``name`` (the prompt itself when
        missing), carrying ``labels`` from the start: a text prompt, or with
        ``chat_role`` a chat prompt of one message with that role."""
        body: dict[str, Any] = {
            "type": "text",
            "name": name,
            "prompt": text,
            "labels": list(labels),
        }
        if chat_role is not None:
            body["type"] = "chat"
            body["prompt"] = [{"role": chat_role, "content": text}]
        if commit_message:
            body["commitMessage"] = commit_message
        response = await self._client.post("v2/prompts", json=body)
        _ = response.raise_for_status()
        return PromptVersion.from_api(response.json())

    async def set_labels(self, name: str, version: int, labels: Sequence[str]) -> None:
        """Move ``labels`` onto ``version``, all in one request."""
        response = await self._client.patch(
            f"{_prompt_path(name)}/versions/{version}",
            json={"newLabels": list(labels)},
        )
        _ = response.raise_for_status()

    async def check_access(self) -> None:
        """The cheapest authenticated read: fails when Langfuse is down or
        rejects the key pair."""
        response = await self._client.get("v2/prompts", params={"limit": 1})
        _ = response.raise_for_status()


def _prompt_path(name: str) -> str:
    return f"v2/prompts/{quote(name, safe='')}"


def default_client() -> LangfusePrompts:
    telemetry = system_config.telemetry
    return LangfusePrompts(
        base_url=telemetry.langfuse_url,
        public_key=telemetry.public_key,
        secret_key=telemetry.secret_key,
    )
