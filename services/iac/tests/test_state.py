# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for terraform state JSON parsing."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from src.state import extract_resource_ids
from src.terraform import CommandResult as CR


EMPTY_STATE = json.dumps({})

NO_RESOURCES_STATE = json.dumps({
    "format_version": "1.0",
    "values": {
        "root_module": {}
    }
})

SINGLE_RESOURCE_STATE = json.dumps({
    "format_version": "1.0",
    "values": {
        "root_module": {
            "resources": [
                {
                    "address": "azurerm_resource_group.main",
                    "mode": "managed",
                    "type": "azurerm_resource_group",
                    "values": {
                        "id": "/subscriptions/sub-1/resourceGroups/rg-main",
                        "name": "rg-main",
                    },
                }
            ]
        }
    }
})

NESTED_MODULES_STATE = json.dumps({
    "format_version": "1.0",
    "values": {
        "root_module": {
            "resources": [
                {
                    "address": "azurerm_resource_group.main",
                    "mode": "managed",
                    "type": "azurerm_resource_group",
                    "values": {"id": "/subscriptions/sub-1/resourceGroups/rg-main"},
                }
            ],
            "child_modules": [
                {
                    "address": "module.network",
                    "resources": [
                        {
                            "address": "module.network.azurerm_virtual_network.vnet",
                            "mode": "managed",
                            "type": "azurerm_virtual_network",
                            "values": {"id": "/subscriptions/sub-1/resourceGroups/rg-main/providers/Microsoft.Network/virtualNetworks/vnet-main"},
                        }
                    ],
                    "child_modules": [
                        {
                            "address": "module.network.module.subnet",
                            "resources": [
                                {
                                    "address": "module.network.module.subnet.azurerm_subnet.snet",
                                    "mode": "managed",
                                    "type": "azurerm_subnet",
                                    "values": {"id": "/subscriptions/sub-1/resourceGroups/rg-main/providers/Microsoft.Network/virtualNetworks/vnet-main/subnets/snet-default"},
                                }
                            ],
                        }
                    ],
                }
            ],
        }
    }
})

DATA_SOURCE_STATE = json.dumps({
    "format_version": "1.0",
    "values": {
        "root_module": {
            "resources": [
                {
                    "address": "data.azurerm_client_config.current",
                    "mode": "data",
                    "type": "azurerm_client_config",
                    "values": {"id": "some-data-source-id"},
                },
                {
                    "address": "azurerm_resource_group.main",
                    "mode": "managed",
                    "type": "azurerm_resource_group",
                    "values": {"id": "/subscriptions/sub-1/resourceGroups/rg-main"},
                },
            ]
        }
    }
})


def test_empty_json_returns_empty_list() -> None:
    assert extract_resource_ids(EMPTY_STATE) == []


def test_no_resources_returns_empty_list() -> None:
    assert extract_resource_ids(NO_RESOURCES_STATE) == []


def test_single_resource_extracted() -> None:
    ids = extract_resource_ids(SINGLE_RESOURCE_STATE)
    assert ids == ["/subscriptions/sub-1/resourceGroups/rg-main"]


def test_nested_modules_extracted_recursively() -> None:
    ids = extract_resource_ids(NESTED_MODULES_STATE)
    assert len(ids) == 3
    assert "/subscriptions/sub-1/resourceGroups/rg-main" in ids
    assert "/subscriptions/sub-1/resourceGroups/rg-main/providers/Microsoft.Network/virtualNetworks/vnet-main" in ids
    assert "/subscriptions/sub-1/resourceGroups/rg-main/providers/Microsoft.Network/virtualNetworks/vnet-main/subnets/snet-default" in ids


def test_data_sources_excluded() -> None:
    ids = extract_resource_ids(DATA_SOURCE_STATE)
    assert ids == ["/subscriptions/sub-1/resourceGroups/rg-main"]
    assert "some-data-source-id" not in ids


def test_invalid_json_returns_empty_list() -> None:
    assert extract_resource_ids("not json at all") == []


def test_resource_without_id_skipped() -> None:
    state = json.dumps({
        "format_version": "1.0",
        "values": {
            "root_module": {
                "resources": [
                    {
                        "address": "null_resource.trigger",
                        "mode": "managed",
                        "type": "null_resource",
                        "values": {},
                    }
                ]
            }
        }
    })
    assert extract_resource_ids(state) == []


@pytest.mark.asyncio
async def test_state_resource_ids_extracts_ids_from_terraform_output() -> None:
    from src.state import state_resource_ids

    with patch(
        "src.state.tf.show_state_json",
        new_callable=AsyncMock,
        return_value=CR(ok=True, stdout=SINGLE_RESOURCE_STATE, stderr="", exit_code=0),
    ):
        result = await state_resource_ids("sh", Path("/fake"))
    assert result.exit_code == 0
    assert json.loads(result.stdout) == ["/subscriptions/sub-1/resourceGroups/rg-main"]


@pytest.mark.asyncio
async def test_state_resource_ids_passes_through_terraform_failure() -> None:
    from src.state import state_resource_ids

    with patch(
        "src.state.tf.show_state_json",
        new_callable=AsyncMock,
        return_value=CR(ok=False, stdout="", stderr="Error: no state", exit_code=1),
    ):
        result = await state_resource_ids("sh", Path("/fake"))
    assert result.exit_code == 1
    assert result.stderr == "Error: no state"
