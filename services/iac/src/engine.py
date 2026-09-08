# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Thin async wrapper around the IaC engine CLI (OpenTofu or Terraform).

Just enough to drive `init`, `validate`, `plan`, `show`, `apply`,
`import`, and `state pull`, one command per call — the flag surface is
identical across both engines, so the caller only picks the binary.
Implementations that need more (state locking, custom backends, policy
as code) should extend this or substitute their own.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from pathlib import Path

_timeout: int | None = None


class EngineTimeoutError(Exception):
    """Raised when an engine command exceeds the configured timeout."""


def set_timeout(seconds: int) -> None:
    global _timeout
    _timeout = seconds if seconds > 0 else None


@dataclass
class CommandResult:
    ok: bool
    stdout: str
    stderr: str
    exit_code: int = 0


async def _run(
    binary: str,
    args: list[str],
    cwd: Path,
    *,
    env: dict[str, str] | None = None,
) -> CommandResult:
    """Run one engine command and capture its output whole.

    The wrapper deliberately logs nothing: stdout/stderr are the job's
    result and are returned to the caller verbatim, and the job layer
    records the outcome. ``communicate()`` reads both pipes to EOF, so
    there is no per-line buffer limit to overrun.
    """
    label = args[0] if args else binary
    t0 = time.monotonic()

    proc = await asyncio.create_subprocess_exec(
        binary,
        *args,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )

    try:
        if _timeout is not None:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=_timeout
            )
        else:
            stdout_bytes, stderr_bytes = await proc.communicate()
    except asyncio.TimeoutError:
        elapsed = time.monotonic() - t0
        try:
            proc.kill()
            await proc.wait()
        except ProcessLookupError:
            pass
        raise EngineTimeoutError(
            f"{binary} {label} timed out after {elapsed:.0f}s (limit={_timeout}s)"
        )
    except BaseException:
        # Reader failure or cancellation: never leave the engine running detached.
        try:
            proc.kill()
            await proc.wait()
        except ProcessLookupError:
            pass
        raise

    exit_code = proc.returncode if proc.returncode is not None else -1
    return CommandResult(
        ok=exit_code == 0,
        stdout=stdout_bytes.decode("utf-8", errors="replace"),
        stderr=stderr_bytes.decode("utf-8", errors="replace"),
        exit_code=exit_code,
    )


def _plan_file_arg(plan_file: str) -> str:
    return f"./{plan_file}"


async def init(
    binary: str,
    cwd: Path,
    *,
    backend_config: str = "",
    env: dict[str, str] | None = None,
) -> CommandResult:
    args = ["init", "-no-color", "-input=false"]
    if backend_config:
        args.append(f"-backend-config={backend_config}")
    return await _run(binary, args, cwd, env=env)


async def validate(
    binary: str, cwd: Path, *, env: dict[str, str] | None = None
) -> CommandResult:
    return await _run(binary, ["validate", "-no-color"], cwd, env=env)


async def plan(
    binary: str,
    cwd: Path,
    targets: list[str],
    plan_file: str,
    *,
    env: dict[str, str] | None = None,
) -> CommandResult:
    args = ["plan", "-no-color", "-input=false", "-out", _plan_file_arg(plan_file)]
    for t in targets:
        args.extend(["-target", t])
    return await _run(binary, args, cwd, env=env)


async def show_plan_json(
    binary: str, cwd: Path, plan_file: str, *, env: dict[str, str] | None = None
) -> CommandResult:
    return await _run(
        binary, ["show", "-json", "-no-color", _plan_file_arg(plan_file)], cwd, env=env
    )


async def show_state_json(
    binary: str, cwd: Path, *, env: dict[str, str] | None = None
) -> CommandResult:
    return await _run(binary, ["show", "-json", "-no-color"], cwd, env=env)


async def apply(
    binary: str, cwd: Path, plan_file: str, *, env: dict[str, str] | None = None
) -> CommandResult:
    return await _run(
        binary,
        [
            "apply",
            "-no-color",
            "-input=false",
            "-auto-approve",
            _plan_file_arg(plan_file),
        ],
        cwd,
        env=env,
    )


async def import_resource(
    binary: str,
    cwd: Path,
    address: str,
    resource_id: str,
    *,
    env: dict[str, str] | None = None,
) -> CommandResult:
    return await _run(
        binary,
        ["import", "-no-color", "-input=false", address, resource_id],
        cwd,
        env=env,
    )


async def state_pull(
    binary: str, cwd: Path, *, env: dict[str, str] | None = None
) -> CommandResult:
    return await _run(binary, ["state", "pull"], cwd, env=env)


def extract_managed_resource_ids(state_json: str) -> list[str]:
    """Provider-assigned ids of every managed resource instance in a
    pulled state document; [] when the state is empty or unparsable."""
    try:
        state = json.loads(state_json)
    except json.JSONDecodeError:
        return []
    if not isinstance(state, dict):
        return []
    ids: list[str] = []
    resources = state.get("resources") or []
    if not isinstance(resources, list):
        return []
    for resource in resources:
        if not isinstance(resource, dict) or resource.get("mode") != "managed":
            continue
        instances = resource.get("instances") or []
        if not isinstance(instances, list):
            continue
        for instance in instances:
            if not isinstance(instance, dict):
                continue
            rid = (instance.get("attributes") or {}).get("id")
            if rid:
                ids.append(rid)
    return ids
