# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Thin async wrapper around the IaC engine CLI (OpenTofu or Terraform).

Just enough to drive `init`, `validate`, `plan`, `show`, and `apply`,
one command per call — the flag surface is identical across both
engines. Implementations that need more (state locking, custom
backends, policy as code) should extend this or substitute their own.

`init`, `plan` and `apply` reach the cloud, so they run with the
request's `scope_id` injected into their environment where the cloud
exposes a provider-level variable that names a scope — Azure and GCP
only (see ``scope_env``). The other providers have no such variable,
so nothing is injected and the command runs on the service's ambient
credentials. `validate` and `show` make no cloud API call and take no
scope at all: they run on the service's own environment, unmodified.
The contract's "Scope injection" section is normative.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path


logger = logging.getLogger("iac.engine")

# Failure diagnostics are passed through verbatim in the job result;
# the console log only carries a tail, to stay readable.
_STDERR_LOG_LIMIT = 500

_SCOPE_ENV_VARS: dict[str, str] = {
    "azure": "ARM_SUBSCRIPTION_ID",
    "gcp": "GOOGLE_PROJECT",
}


def scope_env(terraform_provider: str, scope_id: str) -> dict[str, str]:
    """Environment overlay scoping one command to ``scope_id``.

    Empty for providers with no variable that names a scope, whose
    commands run on the service's ambient credentials instead.
    """
    var = _SCOPE_ENV_VARS.get(terraform_provider)
    if var is None:
        logger.info(
            "no scope variable for provider=%s; command runs on ambient credentials",
            terraform_provider,
        )
        return {}
    return {var: scope_id}


@dataclass
class CommandResult:
    ok: bool
    stdout: str
    stderr: str
    exit_code: int = 0


async def _run(
    binary: str, args: list[str], cwd: Path, env: dict[str, str] | None = None
) -> CommandResult:
    logger.info("run: %s %s (cwd=%s, scope=%s)", binary, " ".join(args), cwd, env or {})
    started = time.monotonic()
    proc = await asyncio.create_subprocess_exec(
        binary,
        *args,
        cwd=str(cwd),
        env=None if env is None else {**os.environ, **env},
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_bytes, stderr_bytes = await proc.communicate()
    duration = time.monotonic() - started
    result = CommandResult(
        ok=proc.returncode == 0,
        stdout=stdout_bytes.decode("utf-8", errors="replace"),
        stderr=stderr_bytes.decode("utf-8", errors="replace"),
        exit_code=proc.returncode if proc.returncode is not None else -1,
    )
    if result.ok:
        logger.info("done: %s %s — exit 0 in %.1fs", binary, args[0], duration)
    else:
        logger.warning(
            "failed: %s %s — exit %d in %.1fs; stderr tail: %s",
            binary,
            args[0],
            result.exit_code,
            duration,
            result.stderr[-_STDERR_LOG_LIMIT:].strip() or "(empty)",
        )
    return result


async def init(binary: str, cwd: Path, env: dict[str, str]) -> CommandResult:
    return await _run(binary, ["init", "-no-color", "-input=false"], cwd, env)


async def validate(binary: str, cwd: Path) -> CommandResult:
    return await _run(binary, ["validate", "-no-color"], cwd)


async def plan(
    binary: str, cwd: Path, targets: list[str], plan_file: str, env: dict[str, str]
) -> CommandResult:
    args = ["plan", "-no-color", "-input=false", "-out", plan_file]
    for t in targets:
        args.extend(["-target", t])
    return await _run(binary, args, cwd, env)


async def show_plan_json(binary: str, cwd: Path, plan_file: str) -> CommandResult:
    return await _run(binary, ["show", "-json", "-no-color", plan_file], cwd)


async def apply(
    binary: str, cwd: Path, plan_file: str, env: dict[str, str]
) -> CommandResult:
    return await _run(
        binary,
        ["apply", "-no-color", "-input=false", "-auto-approve", plan_file],
        cwd,
        env,
    )
