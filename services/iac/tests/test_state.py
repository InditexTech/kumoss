# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Normalization of a pulled state into comparable resource IDs."""

from __future__ import annotations

import json
from typing import Any

import pytest

from src.exceptions import StateReadError
from src.state import StateResourceIds


def _resource(
    mode: str, type_: str, *instances: dict[str, Any], module: str | None = None
) -> dict[str, Any]:
    resource: dict[str, Any] = {
        "mode": mode,
        "type": type_,
        "name": "x",
        "instances": [{"attributes": attributes} for attributes in instances],
    }
    if module is not None:
        resource["module"] = module
    return resource


def _state(*resources: dict[str, Any]) -> str:
    return json.dumps({"version": 4, "resources": list(resources)})


def _ids(state_json: str) -> list[str]:
    return StateResourceIds().read(state_json)


def test_managed_instance_ids_are_listed() -> None:
    state = _state(
        _resource("managed", "azurerm_resource_group", {"id": "/subscriptions/s/rg"}),
        _resource("managed", "azurerm_storage_account", {"id": "/subscriptions/s/sa"}),
    )
    assert _ids(state) == ["/subscriptions/s/rg", "/subscriptions/s/sa"]


def test_data_sources_are_skipped() -> None:
    state = _state(
        _resource("data", "azurerm_client_config", {"id": "cfg"}),
        _resource("managed", "azurerm_resource_group", {"id": "/subscriptions/s/rg"}),
    )
    assert _ids(state) == ["/subscriptions/s/rg"]


def test_arn_is_preferred_over_id() -> None:
    state = _state(
        _resource(
            "managed",
            "aws_instance",
            {"id": "i-0abc", "arn": "arn:aws:ec2:eu-west-1:1:instance/i-0abc"},
        ),
        _resource("managed", "aws_iam_role", {"id": "role", "arn": ""}),
    )
    assert _ids(state) == ["arn:aws:ec2:eu-west-1:1:instance/i-0abc", "role"]


def test_every_instance_of_a_resource_is_listed() -> None:
    state = _state(
        _resource("managed", "aws_subnet", {"id": "subnet-1"}, {"id": "subnet-2"})
    )
    assert _ids(state) == ["subnet-1", "subnet-2"]


def test_child_module_resources_are_included() -> None:
    state = _state(
        _resource(
            "managed",
            "google_compute_network",
            {"id": "projects/p/global/networks/n"},
            module="module.net",
        )
    )
    assert _ids(state) == ["projects/p/global/networks/n"]


def test_duplicates_are_dropped_keeping_first_occurrence() -> None:
    state = _state(
        _resource("managed", "a", {"id": "same"}),
        _resource("managed", "b", {"id": "same"}),
        _resource("managed", "c", {"id": "other"}),
    )
    assert _ids(state) == ["same", "other"]


@pytest.mark.parametrize(
    "attributes",
    [
        pytest.param({}, id="no-id"),
        pytest.param({"id": ""}, id="empty-id"),
        pytest.param({"id": 42}, id="non-string-id"),
    ],
)
def test_instances_without_a_usable_id_are_skipped(attributes: dict[str, Any]) -> None:
    state = _state(_resource("managed", "a", attributes))
    assert _ids(state) == []


def test_missing_instances_or_attributes_are_tolerated() -> None:
    state = json.dumps(
        {
            "version": 4,
            "resources": [
                {"mode": "managed", "type": "a", "name": "x"},
                {"mode": "managed", "type": "b", "name": "y", "instances": [{}]},
                {"mode": "managed", "type": "c", "name": "z", "instances": "nope"},
                "not-a-resource",
            ],
        }
    )
    assert _ids(state) == []


def test_empty_state_yields_empty_list() -> None:
    assert _ids(_state()) == []
    assert _ids(json.dumps({"version": 4})) == []


def test_empty_output_yields_empty_list() -> None:
    assert _ids("") == []
    assert _ids("  \n") == []


@pytest.mark.parametrize("document", ["not json", "[]", "42", '"text"'])
def test_unparsable_document_raises(document: str) -> None:
    with pytest.raises(StateReadError, match="unparsable state document"):
        _ = _ids(document)
