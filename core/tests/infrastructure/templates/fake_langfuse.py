# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""An in-memory Langfuse prompt API behind an httpx transport.

Keeps the rules the seeder and the fetcher rely on: a label names one
version of a prompt at a time (setting it elsewhere takes it off), and
``latest`` is reserved and always on the newest version. Requests go
through the real client, so the paths, query and bodies it sends are
what is under test too.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import unquote

import httpx

from src.infrastructure.templates._langfuse_prompts import LangfusePrompts

PUBLIC_KEY = "pk-lf-test"
SECRET_KEY = "sk-lf-test"


@dataclass
class _Version:
    version: int
    body: Any  # str for a text prompt, a message list for a chat one
    type: str
    labels: set[str] = field(default_factory=set)


class FakeLangfuse:
    def __init__(self) -> None:
        self.prompts: dict[str, list[_Version]] = {}
        self.writes: list[tuple[str, str, Any]] = []
        # Overrides the answer of every request when set.
        self.fail: Callable[[httpx.Request], httpx.Response | None] | None = None

    # --- arranging state ------------------------------------------------

    def add(
        self, name: str, body: Any, labels: tuple[str, ...] = (), type: str = "text"
    ) -> int:
        versions = self.prompts.setdefault(name, [])
        number = len(versions) + 1
        self._move(name, set(labels))
        versions.append(_Version(number, body, type, set(labels)))
        return number

    def labels(self, name: str) -> dict[str, int]:
        """Each label of ``name`` and the version it is on, ``latest`` included."""
        found = {
            label: v.version for v in self.prompts.get(name, []) for label in v.labels
        }
        if self.prompts.get(name):
            found["latest"] = self.prompts[name][-1].version
        return found

    def client(self) -> LangfusePrompts:
        return LangfusePrompts(
            "http://langfuse.invalid/",
            PUBLIC_KEY,
            SECRET_KEY,
            transport=httpx.MockTransport(self._handle),
        )

    # --- the API --------------------------------------------------------

    def _move(self, name: str, labels: set[str]) -> None:
        for v in self.prompts.get(name, []):
            v.labels -= labels

    def _api(self, name: str, v: _Version) -> dict[str, Any]:
        labels = sorted(v.labels)
        if v is self.prompts[name][-1]:
            labels.append("latest")
        return {
            "name": name,
            "version": v.version,
            "type": v.type,
            "prompt": v.body,
            "labels": labels,
            "tags": [],
            "config": {},
        }

    def _handle(self, request: httpx.Request) -> httpx.Response:
        expected = base64.b64encode(f"{PUBLIC_KEY}:{SECRET_KEY}".encode()).decode()
        if request.headers.get("authorization") != f"Basic {expected}":
            return httpx.Response(401, json={"message": "Unauthorized"})
        if self.fail is not None and (failed := self.fail(request)) is not None:
            return failed

        path = request.url.raw_path.decode().split("?")[0]
        prefix = "/api/public/v2/prompts"
        assert path.startswith(prefix), path
        parts = [unquote(p) for p in path[len(prefix) :].split("/") if p]

        if request.method == "GET" and not parts:
            return httpx.Response(200, json={"data": [], "meta": {}})
        if request.method == "GET" and len(parts) == 1:
            return self._get(parts[0], request.url.params.get("label") or "production")
        if request.method == "POST" and not parts:
            return self._create(json.loads(request.content))
        if request.method == "PATCH" and len(parts) == 3 and parts[1] == "versions":
            return self._patch(parts[0], int(parts[2]), json.loads(request.content))
        return httpx.Response(405)

    def _get(self, name: str, label: str) -> httpx.Response:
        versions = self.prompts.get(name)
        if not versions:
            return httpx.Response(404, json={"message": "Prompt not found"})
        if label == "latest":
            return httpx.Response(200, json=self._api(name, versions[-1]))
        for v in versions:
            if label in v.labels:
                return httpx.Response(200, json=self._api(name, v))
        return httpx.Response(404, json={"message": "Prompt not found"})

    def _create(self, body: dict[str, Any]) -> httpx.Response:
        labels = tuple(body.get("labels") or ())
        if "latest" in labels:
            return httpx.Response(400, json={"message": "latest is reserved"})
        existing = self.prompts.get(body["name"])
        if existing and existing[-1].type != body.get("type", "text"):
            # As Langfuse: a prompt keeps the type of its versions.
            return httpx.Response(
                400,
                json={"message": "Previous versions have different prompt type."},
            )
        self.writes.append(("create", body["name"], labels))
        number = self.add(
            body["name"], body["prompt"], labels, body.get("type", "text")
        )
        return httpx.Response(
            201, json=self._api(body["name"], self.prompts[body["name"]][number - 1])
        )

    def _patch(self, name: str, number: int, body: dict[str, Any]) -> httpx.Response:
        labels = set(body.get("newLabels") or ())
        if "latest" in labels:
            return httpx.Response(400, json={"message": "latest is reserved"})
        versions = self.prompts.get(name, [])
        if not 0 < number <= len(versions):
            return httpx.Response(404, json={"message": "Prompt not found"})
        self.writes.append(("label", name, (number, tuple(body["newLabels"]))))
        self._move(name, labels)
        versions[number - 1].labels |= labels
        return httpx.Response(200, json=self._api(name, versions[number - 1]))
