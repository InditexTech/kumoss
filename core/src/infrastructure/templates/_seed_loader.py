# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Discovers and validates seed YAML files used to bootstrap Phoenix.

Each YAML file lives at ``<seed_dir>/<scope>/<type>/<name>.yaml`` and carries
just the prompt body plus an optional description. ``scope``, ``type``, and
``name`` are derived from the file path, not declared in the YAML — that way
a misfiled prompt can't lie about its identity.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml

from src.infrastructure.exceptions import PromptSeedLoadError


Scope = Literal["general", "azure", "gcp"]
PromptType = Literal["guidelines", "resources"]

_VALID_SCOPES: frozenset[str] = frozenset({"general", "azure", "gcp"})
_VALID_TYPES: frozenset[str] = frozenset({"guidelines", "resources"})
# Match the constraints the existing fetcher passes to Phoenix.
_NAME_RE: re.Pattern[str] = re.compile(r"^[a-z0-9_]+$")


@dataclass(frozen=True)
class SeedEntry:
    scope: Scope
    type: PromptType
    name: str
    body: str
    description: str | None
    source: Path  # original file path, for error messages

    @property
    def qualified_name(self) -> str:
        return f"{self.scope}-{self.type}-{self.name}"


class SeedLoader:
    """Walks a seed directory and returns validated SeedEntry objects."""

    def __init__(self, seed_dir: Path):
        self._seed_dir = seed_dir

    def load(self) -> list[SeedEntry]:
        if not self._seed_dir.is_dir():
            raise PromptSeedLoadError(
                message=f"Seed directory does not exist: {self._seed_dir}",
                error_code=500,
            )

        entries: list[SeedEntry] = []
        seen: dict[str, Path] = {}

        for path in sorted(self._seed_dir.rglob("*.yaml")):
            entry = self._parse(path)
            if entry.qualified_name in seen:
                raise PromptSeedLoadError(
                    message=(
                        f"Duplicate qualified name '{entry.qualified_name}' "
                        f"from {path} and {seen[entry.qualified_name]}"
                    ),
                    error_code=500,
                )
            seen[entry.qualified_name] = path
            entries.append(entry)

        return entries

    def _parse(self, path: Path) -> SeedEntry:
        try:
            rel_parts = path.relative_to(self._seed_dir).parts
        except ValueError as e:
            raise PromptSeedLoadError(
                message=f"Seed file {path} is not under {self._seed_dir}",
                error_code=500,
            ) from e

        if len(rel_parts) != 3:
            raise PromptSeedLoadError(
                message=(
                    f"Seed file path must be <scope>/<type>/<name>.yaml; got {path} "
                    f"(relative: {'/'.join(rel_parts)})"
                ),
                error_code=500,
            )

        scope, type_, filename = rel_parts
        if scope not in _VALID_SCOPES:
            raise PromptSeedLoadError(
                message=f"Invalid scope '{scope}' in {path}; expected one of {sorted(_VALID_SCOPES)}",
                error_code=500,
            )
        if type_ not in _VALID_TYPES:
            raise PromptSeedLoadError(
                message=f"Invalid type '{type_}' in {path}; expected one of {sorted(_VALID_TYPES)}",
                error_code=500,
            )

        name = filename.removesuffix(".yaml")
        if not _NAME_RE.match(name):
            raise PromptSeedLoadError(
                message=(
                    f"Invalid prompt name '{name}' in {path}; "
                    f"must match {_NAME_RE.pattern}"
                ),
                error_code=500,
            )

        try:
            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise PromptSeedLoadError(
                message=f"YAML parse error in {path}: {e}",
                error_code=500,
            ) from e

        if not isinstance(data, dict):
            raise PromptSeedLoadError(
                message=f"Top-level YAML in {path} must be a mapping (got {type(data).__name__})",
                error_code=500,
            )

        body = data.get("body")
        if not isinstance(body, str) or not body.strip():
            raise PromptSeedLoadError(
                message=f"'body' in {path} must be a non-empty string",
                error_code=500,
            )

        description = data.get("description")
        if description is not None and not isinstance(description, str):
            raise PromptSeedLoadError(
                message=f"'description' in {path} must be a string when present",
                error_code=500,
            )

        return SeedEntry(
            scope=scope,  # type: ignore[arg-type]
            type=type_,  # type: ignore[arg-type]
            name=name,
            body=body,
            description=description,
            source=path,
        )
