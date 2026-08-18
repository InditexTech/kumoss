# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""AWS resource listing via the ``aws`` CLI."""

from __future__ import annotations

import asyncio
import json

from .terraform import CommandResult


async def list_resource_ids(scope_id: str) -> CommandResult:
    """List all resource ARNs in an AWS account.

    Runs ``aws resourcegroupstaggingapi get-resources`` and extracts
    the ARN from each tagged resource.  Credential resolution uses
    the standard AWS env vars (``AWS_ACCESS_KEY_ID``,
    ``AWS_SECRET_ACCESS_KEY``, ``AWS_SESSION_TOKEN``) or instance
    profile / role assumption.
    """
    proc = await asyncio.create_subprocess_exec(
        "aws", "resourcegroupstaggingapi", "get-resources",
        "--output", "json",
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
        data = json.loads(stdout)
        arns = [
            mapping["ResourceARN"]
            for mapping in data.get("ResourceTagMappingList", [])
            if "ResourceARN" in mapping
        ]
        return CommandResult(
            ok=True, stdout=json.dumps(arns), stderr=stderr, exit_code=0
        )
    except (json.JSONDecodeError, KeyError, TypeError):
        return CommandResult(ok=False, stdout=stdout, stderr=stderr, exit_code=1)
