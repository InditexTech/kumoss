# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Thin async wrapper around the IaC engine CLI (OpenTofu or Terraform).

Just enough to drive `init`, `validate`, `plan`, `show`, `apply`,
`import`, and `state pull`, one command per call — the flag surface is
identical across both engines. Implementations that need more (state
locking, custom backends, policy as code) should extend this or
substitute their own.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class CommandResult:
    ok: bool
    stdout: str
    stderr: str
    exit_code: int = 0


async def _run(binary: str, args: list[str], cwd: Path) -> CommandResult:
    proc = await asyncio.create_subprocess_exec(
        binary,
        *args,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_bytes, stderr_bytes = await proc.communicate()
    return CommandResult(
        ok=proc.returncode == 0,
        stdout=stdout_bytes.decode("utf-8", errors="replace"),
        stderr=stderr_bytes.decode("utf-8", errors="replace"),
        exit_code=proc.returncode if proc.returncode is not None else -1,
    )


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


async def import_resource(
    binary: str, cwd: Path, address: str, resource_id: str
) -> CommandResult:
    return await _run(
        binary,
        ["import", "-no-color", "-input=false", address, resource_id],
        cwd,
    )


async def state_pull(binary: str, cwd: Path) -> CommandResult:
    return await _run(binary, ["state", "pull"], cwd)


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
