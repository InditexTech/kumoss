# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Shape of the import request models against the contract."""

from __future__ import annotations

from typing import Any, get_args

import pytest
from pydantic import ValidationError

from src.models import (
    ImportRequest,
    JobKind,
    ScopeResourceIdsRequest,
    StateResourceIdsRequest,
)

SCOPE: dict[str, Any] = {"scope_id": "sub-1", "terraform_provider": "azure"}


def test_import_request_carries_address_and_resource_id() -> None:
    request = ImportRequest(
        workspace_path="/ws",
        address="azurerm_resource_group.main",
        resource_id="/subscriptions/x/resourceGroups/y",
        **SCOPE,
    )
    assert request.address == "azurerm_resource_group.main"
    assert request.resource_id == "/subscriptions/x/resourceGroups/y"


@pytest.mark.parametrize("missing", ["address", "resource_id", "scope_id"])
def test_import_request_requires_every_field(missing: str) -> None:
    body: dict[str, str] = {
        "workspace_path": "/ws",
        "address": "azurerm_resource_group.main",
        "resource_id": "/subscriptions/x/resourceGroups/y",
        **SCOPE,
    }
    del body[missing]
    with pytest.raises(ValidationError):
        _ = ImportRequest.model_validate(body)


def test_import_request_rejects_empty_address() -> None:
    with pytest.raises(ValidationError):
        _ = ImportRequest(
            workspace_path="/ws", address="", resource_id="/subscriptions/x", **SCOPE
        )


@pytest.mark.parametrize("field", ["scope_id", "terraform_provider"])
def test_state_resource_ids_request_rejects_scope_fields(field: str) -> None:
    with pytest.raises(ValidationError):
        _ = StateResourceIdsRequest.model_validate(
            {"workspace_path": "/ws", field: SCOPE[field]}
        )


def test_state_resource_ids_request_needs_only_the_workspace() -> None:
    request = StateResourceIdsRequest(workspace_path="/ws")
    assert request.workspace_path == "/ws"


@pytest.mark.parametrize("missing", ["scope_id", "terraform_provider"])
def test_scope_resource_ids_request_requires_the_scope(missing: str) -> None:
    body: dict[str, str] = {"workspace_path": "/ws", **SCOPE}
    del body[missing]
    with pytest.raises(ValidationError):
        _ = ScopeResourceIdsRequest.model_validate(body)


def test_scope_resource_ids_request_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError):
        _ = ScopeResourceIdsRequest.model_validate(
            {"workspace_path": "/ws", "address": "x", **SCOPE}
        )


def test_job_kind_includes_the_import_kinds() -> None:
    assert {"import", "state_resource_ids", "scope_resource_ids"} <= set(
        get_args(JobKind)
    )
