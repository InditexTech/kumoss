# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Thin async wrapper around the IaC engine CLI (OpenTofu or Terraform).

Just enough to drive `init`, `validate`, `plan`, `show`, and `apply`,
one command per call — the flag surface is identical across both
engines. Implementations that need more (state locking, custom
backends, policy as code) should extend this or substitute their own.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from pathlib import Path


logger = logging.getLogger("iac.engine")

# Failure diagnostics are passed through verbatim in the job result;
# the console log only carries a tail, to stay readable.
_STDERR_LOG_LIMIT = 500


@dataclass
class CommandResult:
    ok: bool
    stdout: str
    stderr: str
    exit_code: int = 0


async def _run(binary: str, args: list[str], cwd: Path) -> CommandResult:
    logger.info("run: %s %s (cwd=%s)", binary, " ".join(args), cwd)
    started = time.monotonic()
    proc = await asyncio.create_subprocess_exec(
        binary,
        *args,
        cwd=str(cwd),
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


async def init(binary: str, cwd: Path) -> CommandResult:
    return await _run(binary, ["init", "-no-color", "-input=false"], cwd)


async def validate(binary: str, cwd: Path) -> CommandResult:
    return await _run(binary, ["validate", "-no-color"], cwd)


async def plan(
    binary: str, cwd: Path, targets: list[str], plan_file: str
) -> CommandResult:
    args = ["plan", "-no-color", "-input=false", "-out", plan_file]
    for t in targets:
        args.extend(["-target", t])
    return await _run(binary, args, cwd)


async def show_plan_json(binary: str, cwd: Path, plan_file: str) -> CommandResult:
    return await _run(binary, ["show", "-json", "-no-color", plan_file], cwd)


async def apply(binary: str, cwd: Path, plan_file: str) -> CommandResult:
    return await _run(
        binary,
        ["apply", "-no-color", "-input=false", "-auto-approve", plan_file],
        cwd,
    )
