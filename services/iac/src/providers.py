# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Cloud provider detection and scope resource dispatch."""

from __future__ import annotations

import re
from pathlib import Path

from . import aws
from . import azure
from . import gcp
from .terraform import CommandResult

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_AWS_ACCOUNT_RE = re.compile(r"^\d{12}$")


def detect_provider_from_scope(scope_id: str) -> str:
    """Infer cloud provider from scope_id format.

    - UUID (8-4-4-4-12 hex) → ``"azurerm"`` (Azure subscription ID)
    - 12-digit number → ``"aws"`` (AWS account ID)
    - Anything else → ``"google"`` (GCP project ID)
    """
    if _UUID_RE.match(scope_id):
        return "azurerm"
    if _AWS_ACCOUNT_RE.match(scope_id):
        return "aws"
    return "google"


async def scope_resource_ids(workspace: Path, scope_id: str) -> CommandResult:
    """Composite pipeline: detect provider from scope_id → dispatch to cloud module."""
    provider = detect_provider_from_scope(scope_id)

    if provider == "azurerm":
        return await azure.list_resource_ids(scope_id)
    if provider == "google":
        return await gcp.list_resource_ids(scope_id)
    if provider == "aws":
        return await aws.list_resource_ids(scope_id)

    return CommandResult(
        ok=False,
        stdout="",
        stderr=f"Scope resource listing not implemented for provider: {provider}",
        exit_code=1,
    )
