# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Azure resource listing via the ``az`` CLI."""

from __future__ import annotations

import asyncio
import os

from .terraform import CommandResult


async def _az_login() -> CommandResult | None:
    """Log in with the service principal from ``ARM_*`` env vars.

    Returns ``None`` on success or a ``CommandResult`` describing the
    failure.
    """
    client_id = os.environ.get("ARM_CLIENT_ID", "")
    client_secret = os.environ.get("ARM_CLIENT_SECRET", "")
    tenant_id = os.environ.get("ARM_TENANT_ID", "")

    if not all([client_id, client_secret, tenant_id]):
        return CommandResult(
            ok=False,
            stdout="",
            stderr=(
                "Azure login skipped: ARM_CLIENT_ID, ARM_CLIENT_SECRET, "
                "and ARM_TENANT_ID must all be set."
            ),
            exit_code=1,
        )

    proc = await asyncio.create_subprocess_exec(
        "az", "login", "--service-principal",
        "-u", client_id,
        "-p", client_secret,
        "--tenant", tenant_id,
        "--allow-no-subscriptions",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr_bytes = await proc.communicate()
    if proc.returncode != 0:
        return CommandResult(
            ok=False,
            stdout="",
            stderr=stderr_bytes.decode("utf-8", errors="replace"),
            exit_code=proc.returncode if proc.returncode is not None else 1,
        )
    return None


async def list_resource_ids(scope_id: str) -> CommandResult:
    """List all resource IDs in an Azure subscription.

    Authenticates via ``az login --service-principal`` using the
    ``ARM_CLIENT_ID`` / ``ARM_CLIENT_SECRET`` / ``ARM_TENANT_ID`` env
    vars, then runs ``az resource list``.
    """
    login_err = await _az_login()
    if login_err is not None:
        return login_err

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
