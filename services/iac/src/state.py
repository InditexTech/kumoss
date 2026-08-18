# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Terraform state inspection: extract resource IDs from state JSON."""

from __future__ import annotations

import json
from pathlib import Path

from . import terraform as tf
from .terraform import CommandResult


def extract_resource_ids(state_json: str) -> list[str]:
    """Parse ``terraform show -json`` output and return managed resource IDs.

    Walks the module tree recursively. Only ``mode == "managed"``
    resources are included (data sources are skipped). Resources whose
    ``values`` dict has no ``id`` key are silently skipped.
    """
    try:
        data = json.loads(state_json)
    except (json.JSONDecodeError, TypeError):
        return []

    values = data.get("values")
    if not values:
        return []

    root = values.get("root_module")
    if not root:
        return []

    ids: list[str] = []
    _collect_ids(root, ids)
    return ids


def _collect_ids(module: dict, ids: list[str]) -> None:
    for resource in module.get("resources", []):
        if resource.get("mode") != "managed":
            continue
        resource_id = resource.get("values", {}).get("id")
        if resource_id:
            ids.append(resource_id)
    for child in module.get("child_modules", []):
        _collect_ids(child, ids)


async def state_resource_ids(binary: str, workspace: Path) -> CommandResult:
    """Composite pipeline: show state → extract IDs → JSON array."""
    result = await tf.show_state_json(binary, workspace)
    if result.exit_code != 0:
        return result
    ids = extract_resource_ids(result.stdout)
    return CommandResult(
        ok=True, stdout=json.dumps(ids), stderr=result.stderr, exit_code=0
    )
