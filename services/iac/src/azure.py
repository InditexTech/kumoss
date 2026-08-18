# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Azure resource listing via the ``az`` CLI."""

from __future__ import annotations

import asyncio

from .terraform import CommandResult


async def list_resource_ids(scope_id: str) -> CommandResult:
    """List all resource IDs in an Azure subscription.

    Runs ``az resource list --subscription <scope_id> --query "[].id"``
    and returns the raw JSON array of ID strings.  Credential resolution
    uses the standard ``az`` login context (service principal env vars
    ``ARM_CLIENT_ID`` / ``ARM_CLIENT_SECRET`` / ``ARM_TENANT_ID``, or
    managed identity).
    """
    proc = await asyncio.create_subprocess_exec(
        "az", "resource", "list",
        "--subscription", scope_id,
        "--query", "[].id",
        "-o", "json",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_bytes, stderr_bytes = await proc.communicate()
    exit_code = proc.returncode if proc.returncode is not None else -1
    return CommandResult(
        ok=exit_code == 0,
        stdout=stdout_bytes.decode("utf-8", errors="replace"),
        stderr=stderr_bytes.decode("utf-8", errors="replace"),
        exit_code=exit_code,
    )
