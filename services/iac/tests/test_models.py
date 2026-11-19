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
    InitRequest,
    JobKind,
    ProviderScope,
    ScopeResourceIdsRequest,
    StateResourceIdsRequest,
)

SCOPE: dict[str, Any] = {"scopes": [{"provider": "azurerm", "scope_id": "sub-1"}]}
DISCOVERY_SCOPE: dict[str, Any] = {"scope_id": "sub-1", "provider": "azurerm"}


def test_import_request_carries_address_and_resource_id() -> None:
    request = ImportRequest(
        workspace_path="/ws",
        address="azurerm_resource_group.main",
        resource_id="/subscriptions/x/resourceGroups/y",
        **SCOPE,
    )
    assert request.address == "azurerm_resource_group.main"
    assert request.resource_id == "/subscriptions/x/resourceGroups/y"


@pytest.mark.parametrize("missing", ["address", "resource_id"])
def test_import_request_requires_every_field(missing: str) -> None:
    body: dict[str, Any] = {
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


def test_scopes_default_to_empty() -> None:
    assert InitRequest(workspace_path="/ws").scopes == []


def test_scopes_keep_their_order() -> None:
    request = InitRequest.model_validate(
        {
            "workspace_path": "/ws",
            "scopes": [
                {"provider": "google", "scope_id": "p"},
                {"provider": "azurerm", "scope_id": "s"},
            ],
        }
    )
    assert request.scopes == [
        ProviderScope(provider="google", scope_id="p"),
        ProviderScope(provider="azurerm", scope_id="s"),
    ]


def test_a_provider_may_appear_only_once() -> None:
    with pytest.raises(ValidationError, match="'google' appears more than once"):
        _ = InitRequest.model_validate(
            {
                "workspace_path": "/ws",
                "scopes": [
                    {"provider": "google", "scope_id": "p-1"},
                    {"provider": "google", "scope_id": "p-2"},
                ],
            }
        )


@pytest.mark.parametrize(
    "provider",
    ["azurerm", "google", "aws", "oci", "kubernetes", "vsphere", "a", "my_prov-1"],
)
def test_provider_scope_accepts_terraform_type_names(provider: str) -> None:
    assert ProviderScope(provider=provider, scope_id="s").provider == provider


@pytest.mark.parametrize(
    "provider", ["", "AzureRM", "hashicorp/azurerm", "-x", "_x", "a" * 65, "a b"]
)
def test_provider_scope_rejects_other_names(provider: str) -> None:
    with pytest.raises(ValidationError):
        _ = ProviderScope(provider=provider, scope_id="s")


@pytest.mark.parametrize(
    "field", [SCOPE, {"scopes": []}, {"scope_id": "s"}, {"provider": "azurerm"}]
)
def test_state_resource_ids_request_rejects_scope_fields(field: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        _ = StateResourceIdsRequest.model_validate({"workspace_path": "/ws", **field})


def test_state_resource_ids_request_needs_only_the_workspace() -> None:
    request = StateResourceIdsRequest(workspace_path="/ws")
    assert request.workspace_path == "/ws"


@pytest.mark.parametrize("missing", ["scope_id", "provider"])
def test_scope_resource_ids_request_requires_the_scope(missing: str) -> None:
    body: dict[str, str] = {"workspace_path": "/ws", **DISCOVERY_SCOPE}
    del body[missing]
    with pytest.raises(ValidationError):
        _ = ScopeResourceIdsRequest.model_validate(body)


def test_scope_resource_ids_request_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError):
        _ = ScopeResourceIdsRequest.model_validate(
            {"workspace_path": "/ws", "address": "x", **DISCOVERY_SCOPE}
        )


@pytest.mark.parametrize("provider", ["azure", "gcp", "oci", "kubernetes"])
def test_scope_resource_ids_request_takes_only_listable_providers(
    provider: str,
) -> None:
    with pytest.raises(ValidationError):
        _ = ScopeResourceIdsRequest.model_validate(
            {"workspace_path": "/ws", "scope_id": "s", "provider": provider}
        )


def test_job_kind_includes_the_import_kinds() -> None:
    assert {"import", "state_resource_ids", "scope_resource_ids"} <= set(
        get_args(JobKind)
    )
