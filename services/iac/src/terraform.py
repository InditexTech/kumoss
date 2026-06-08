# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Thin async wrapper around the terraform CLI.

Just enough to drive `init`, `validate`, `plan`, and to read back the
plan JSON for drift detection. Implementations that need more (state
locking, custom backends, policy as code) should extend this or
substitute their own.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass
from pathlib import Path


@dataclass
class CommandResult:
    ok: bool
    stdout: str
    stderr: str


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


def parse_drift(plan_json_text: str) -> list[dict]:
    """Return resource_changes entries that aren't no-ops.

    Equivalent to the existing core's TerraformUtils.plan_to_drift; kept
    minimal here so the service has no shared dependencies.
    """
    try:
        plan = json.loads(plan_json_text)
    except json.JSONDecodeError:
        return []
    changes = plan.get("resource_changes") or []
    drift: list[dict] = []
    for entry in changes:
        actions = (entry.get("change") or {}).get("actions") or []
        if actions and actions != ["no-op"]:
            drift.append(
                {
                    "address": entry.get("address"),
                    "actions": actions,
                }
            )
    return drift


def random_plan_filename() -> str:
    return f"{uuid.uuid4().hex}.plan"
