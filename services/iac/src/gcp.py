# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""GCP resource listing via the ``gcloud`` CLI."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path

from .terraform import CommandResult


async def _gcloud_auth() -> CommandResult | None:
    """Activate a GCP service account from env vars.

    Checks ``GOOGLE_APPLICATION_CREDENTIALS`` (path to a key file) first,
    then ``GOOGLE_CREDENTIALS`` (inline JSON).  Returns ``None`` on
    success or a ``CommandResult`` describing the failure.
    """
    key_file = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
    key_json = os.environ.get("GOOGLE_CREDENTIALS", "")

    if not key_file and not key_json:
        return CommandResult(
            ok=False,
            stdout="",
            stderr=(
                "GCP auth skipped: set GOOGLE_APPLICATION_CREDENTIALS "
                "(path) or GOOGLE_CREDENTIALS (inline JSON)."
            ),
            exit_code=1,
        )

    tmp_key_path: Path | None = None
    try:
        if not key_file and key_json:
            tmp = tempfile.NamedTemporaryFile(
                suffix=".json", delete=False, mode="w",
            )
            tmp.write(key_json)
            tmp.close()
            tmp_key_path = Path(tmp.name)
            key_file = str(tmp_key_path)

        proc = await asyncio.create_subprocess_exec(
            "gcloud", "auth", "activate-service-account",
            f"--key-file={key_file}",
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
    finally:
        if tmp_key_path is not None:
            tmp_key_path.unlink(missing_ok=True)


async def list_resource_ids(scope_id: str) -> CommandResult:
    """List all resource names in a GCP project.

    Activates a service account from ``GOOGLE_APPLICATION_CREDENTIALS``
    or ``GOOGLE_CREDENTIALS``, then runs
    ``gcloud asset search-all-resources``.
    """
    auth_err = await _gcloud_auth()
    if auth_err is not None:
        return auth_err

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
