# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Discovers and validates seed files used to bootstrap Langfuse.

Each seed lives at ``<seed_dir>/<scope>/<type>/<name>.<ext>``. ``scope``,
``type``, and ``name`` are derived from the file path, not declared in the
file — that way a misfiled prompt can't lie about its identity.

Prompts are YAML files carrying the prompt body plus an optional
description. Policies (type ``policies``) are plain Rego files whose whole
text is the body, so ``opa test`` and ``opa fmt`` run on the very file that
is seeded.

The Langfuse prompt name mirrors the path, ``<scope>/<type>/<name>``:
Langfuse shows each ``/``-separated segment as a folder, so the prompt
list is browsed the way the seed directory is laid out.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml

from src.infrastructure.exceptions import PromptSeedLoadError


# "general", or a Terraform provider type name (azurerm, google, aws...): the
# provider whose sessions use the prompt. Any provider may have prompts.
Scope = str
PromptType = Literal["guidelines", "resources", "compliance", "policies"]

_SCOPE_RE: re.Pattern[str] = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
# The name part of the prompt names the fetcher asks Langfuse for.
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
        return prompt_name(self.scope, self.type, self.name)


def prompt_name(scope: str, type: str, name: str) -> str:
    """The Langfuse name of a prompt: a folder per scope, then per type."""
    return f"{scope}/{type}/{name}"


class SeedLoader:
    """Walks a seed directory and returns validated SeedEntry objects."""

    # The file extension each type is seeded from.
    _TYPE_SUFFIXES: dict[str, str] = {
        "guidelines": ".yaml",
        "resources": ".yaml",
        "compliance": ".yaml",
        "policies": ".rego",
    }

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

        paths = (
            p
            for p in self._seed_dir.rglob("*")
            if p.is_file() and p.suffix in set(self._TYPE_SUFFIXES.values())
        )
        for path in sorted(paths):
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
                    f"Seed file path must be <scope>/<type>/<name>.<ext>; got {path} "
                    f"(relative: {'/'.join(rel_parts)})"
                ),
                error_code=500,
            )

        scope, type_, filename = rel_parts
        if not _SCOPE_RE.match(scope):
            raise PromptSeedLoadError(
                message=f"Invalid scope '{scope}' in {path}; expected 'general' or a "
                + "Terraform provider type name (e.g. azurerm)",
                error_code=500,
            )
        if type_ not in self._TYPE_SUFFIXES:
            raise PromptSeedLoadError(
                message=f"Invalid type '{type_}' in {path}; expected one of {sorted(self._TYPE_SUFFIXES)}",
                error_code=500,
            )
        suffix = self._TYPE_SUFFIXES[type_]
        if path.suffix != suffix:
            raise PromptSeedLoadError(
                message=f"Seed files of type '{type_}' must be {suffix} files; got {path}",
                error_code=500,
            )

        name = filename.removesuffix(suffix)
        if not _NAME_RE.match(name):
            raise PromptSeedLoadError(
                message=(
                    f"Invalid prompt name '{name}' in {path}; "
                    f"must match {_NAME_RE.pattern}"
                ),
                error_code=500,
            )

        if suffix == ".rego":
            return self._policy(path, scope, name)

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

    def _policy(self, path: Path, scope: Scope, name: str) -> SeedEntry:
        body = path.read_text(encoding="utf-8")
        if not body.strip():
            raise PromptSeedLoadError(
                message=f"Policy {path} is empty",
                error_code=500,
            )
        return SeedEntry(
            scope=scope,
            type="policies",
            name=name,
            body=body,
            description=f"Rego policy evaluated by OPA ({name}).",
            source=path,
        )
