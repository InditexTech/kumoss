# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""``CloudProvider`` contract plus the subprocess and result helpers every
provider module shares.

Provider modules import ``_run``, ``_failure`` and ``_ids_result`` by name
(``from ._base import _run``) and call the bare name. Tests rely on that:
they patch ``src.cloud_cli._azure._run`` (and friends) to intercept the
CLI call made by exactly one provider.
"""

from __future__ import annotations

import asyncio
import json
import shutil
from abc import ABC, abstractmethod
from typing import ClassVar

from ..config import Config
from ..engine import CommandResult


async def _run(args: list[str], *, env: dict[str, str] | None = None) -> CommandResult:
    """Run one CLI command and capture its outcome without raising."""
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    stdout_bytes, stderr_bytes = await proc.communicate()
    return CommandResult(
        ok=proc.returncode == 0,
        stdout=stdout_bytes.decode("utf-8", errors="replace"),
        stderr=stderr_bytes.decode("utf-8", errors="replace"),
        exit_code=proc.returncode if proc.returncode is not None else -1,
    )


def _failure(stderr: str, exit_code: int = 1) -> CommandResult:
    return CommandResult(ok=False, stdout="", stderr=stderr, exit_code=exit_code)


def _ids_result(ids: list[str]) -> CommandResult:
    """Success result whose stdout is the JSON array of resource ids."""
    return CommandResult(ok=True, stdout=json.dumps(ids), stderr="", exit_code=0)


class CloudProvider(ABC):
    """One cloud CLI: credential readiness, login, scope env, listing.

    Every answer comes from ``config``; providers never read
    ``os.environ`` so that readiness is decided once, at startup, from
    the same values the engine will receive.
    """

    name: ClassVar[str]  # contract vocabulary: "azure" | "gcp" | "aws"
    display_name: ClassVar[str]  # "Azure" | "GCP" | "AWS", for logs and errors
    cli_binary: ClassVar[str]  # "az" | "gcloud" | "aws"

    def __init__(self, config: Config) -> None:
        self._config = config

    @abstractmethod
    def credential_env(self) -> dict[str, str]:
        """Required env var name -> current value (``""`` when unset)."""

    def missing_env(self) -> list[str]:
        """Names in ``credential_env()`` whose value is empty."""
        return [name for name, value in self.credential_env().items() if not value]

    def is_configured(self) -> bool:
        """At least one credential var is set."""
        return any(self.credential_env().values())

    def is_ready(self) -> bool:
        """Every credential var is set."""
        return not self.missing_env()

    def cli_available(self) -> bool:
        return shutil.which(self.cli_binary) is not None

    @abstractmethod
    async def login(self) -> None:
        """Authenticate the CLI. Raises ``RuntimeError`` on failure."""

    @abstractmethod
    async def scope_env(self, scope_id: str) -> dict[str, str]:
        """Extra engine env for a job scoped to *scope_id*."""

    @abstractmethod
    async def list_resource_ids(self, scope_id: str) -> CommandResult:
        """JSON array of resource ids on stdout, or a failure result."""
