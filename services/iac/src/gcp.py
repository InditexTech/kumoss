# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""GCP resource listing via the ``gcloud`` CLI."""

from __future__ import annotations

import asyncio
import json

from .terraform import CommandResult


async def list_resource_ids(scope_id: str) -> CommandResult:
    """List all resource names in a GCP project.

    Runs ``gcloud asset search-all-resources`` and transforms the
    output into a flat JSON array of asset name strings.  Credential
    resolution uses ``GOOGLE_APPLICATION_CREDENTIALS`` or the default
    ``gcloud`` auth context.
    """
    proc = await asyncio.create_subprocess_exec(
        "gcloud", "asset", "search-all-resources",
        f"--scope=projects/{scope_id}",
        "--format=json(name)",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_bytes, stderr_bytes = await proc.communicate()
    exit_code = proc.returncode if proc.returncode is not None else -1
    stdout = stdout_bytes.decode("utf-8", errors="replace")
    stderr = stderr_bytes.decode("utf-8", errors="replace")

    if exit_code != 0:
        return CommandResult(ok=False, stdout=stdout, stderr=stderr, exit_code=exit_code)

    try:
        entries = json.loads(stdout)
        ids = [entry["name"] for entry in entries if "name" in entry]
        return CommandResult(
            ok=True, stdout=json.dumps(ids), stderr=stderr, exit_code=0
        )
    except (json.JSONDecodeError, KeyError, TypeError):
        return CommandResult(ok=False, stdout=stdout, stderr=stderr, exit_code=1)
