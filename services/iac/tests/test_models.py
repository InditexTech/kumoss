# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Shape of the request models against the contract."""

from __future__ import annotations

from typing import Any, get_args

import pytest
from pydantic import ValidationError

from src.models import (
    ApplyRequest,
    ImportRequest,
    InitRequest,
    JobKind,
    PlanRequest,
    ScopeResourceIdsRequest,
    ShowRequest,
    StateResourceIdsRequest,
    ValidateRequest,
)

DISCOVERY_SCOPE: dict[str, Any] = {"scope_id": "sub-1", "provider": "azurerm"}
IMPORT: dict[str, Any] = {
    "workspace_path": "/ws",
    "address": "azurerm_resource_group.main",
    "resource_id": "/subscriptions/x/resourceGroups/y",
}


def test_import_request_carries_address_and_resource_id() -> None:
    request = ImportRequest.model_validate(IMPORT)
    assert request.address == "azurerm_resource_group.main"
    assert request.resource_id == "/subscriptions/x/resourceGroups/y"


@pytest.mark.parametrize("missing", ["address", "resource_id"])
def test_import_request_requires_every_field(missing: str) -> None:
    body = dict(IMPORT)
    del body[missing]
    with pytest.raises(ValidationError):
        _ = ImportRequest.model_validate(body)


def test_import_request_rejects_empty_address() -> None:
    with pytest.raises(ValidationError):
        _ = ImportRequest.model_validate({**IMPORT, "address": ""})


@pytest.mark.parametrize(
    ("model", "extra"),
    [
        (InitRequest, {}),
        (ValidateRequest, {}),
        (ShowRequest, {"plan_file": "p.plan"}),
        (ApplyRequest, {"plan_file": "p.plan"}),
        (PlanRequest, {"plan_file": "p.plan"}),
        (ImportRequest, {"address": "a.b", "resource_id": "i"}),
    ],
)
def test_every_command_takes_env(model: Any, extra: dict[str, Any]) -> None:
    request = model.model_validate(
        {"workspace_path": "/ws", "env": {"GOOGLE_PROJECT": "p"}, **extra}
    )
    assert request.env == {"GOOGLE_PROJECT": "p"}
    assert model.model_validate({"workspace_path": "/ws", **extra}).env == {}


@pytest.mark.parametrize("name", ["", "1X", "A-B", "A B", "A=B", "X" * 129])
def test_env_names_are_plain_identifiers(name: str) -> None:
    with pytest.raises(ValidationError):
        _ = InitRequest.model_validate({"workspace_path": "/ws", "env": {name: "v"}})


def test_env_values_are_strings() -> None:
    with pytest.raises(ValidationError):
        _ = InitRequest.model_validate({"workspace_path": "/ws", "env": {"X": 1}})


def test_vars_take_any_json_value_and_stay_out_of_repr() -> None:
    request = PlanRequest.model_validate(
        {
            "workspace_path": "/ws",
            "plan_file": "p.plan",
            "vars": {"pw": "s3cr3t", "net": {"ips": ["1.2.3.4/32"]}, "n": 3},
        }
    )
    assert request.vars["net"] == {"ips": ["1.2.3.4/32"]}
    assert "s3cr3t" not in repr(request)


def test_env_stays_out_of_repr() -> None:
    request = InitRequest.model_validate(
        {"workspace_path": "/ws", "env": {"TOKEN_X": "s3cr3t"}}
    )
    assert "s3cr3t" not in repr(request)


@pytest.mark.parametrize(
    ("model", "extra"),
    [
        (InitRequest, {}),
        (ValidateRequest, {}),
        (ShowRequest, {"plan_file": "p.plan"}),
        (ApplyRequest, {"plan_file": "p.plan"}),
    ],
)
def test_commands_that_evaluate_nothing_reject_vars(
    model: Any, extra: dict[str, Any]
) -> None:
    with pytest.raises(ValidationError):
        _ = model.model_validate({"workspace_path": "/ws", "vars": {"a": 1}, **extra})


@pytest.mark.parametrize(
    "field",
    [
        {"scopes": [{"provider": "azurerm", "scope_id": "s"}]},
        {"var_files": ["envs/dev.tfvars"]},
        {"variables": {"a": 1}},
    ],
)
def test_pre_2_0_fields_are_rejected(field: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        _ = PlanRequest.model_validate(
            {"workspace_path": "/ws", "plan_file": "p.plan", **field}
        )


@pytest.mark.parametrize(
    "field",
    [{"env": {"X": "1"}}, {"scope_id": "s"}, {"provider": "azurerm"}],
)
def test_state_resource_ids_request_rejects_other_fields(
    field: dict[str, Any],
) -> None:
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


@pytest.mark.parametrize("field", [{"address": "x"}, {"env": {"X": "1"}}])
def test_scope_resource_ids_request_forbids_extra_fields(
    field: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError):
        _ = ScopeResourceIdsRequest.model_validate(
            {"workspace_path": "/ws", **field, **DISCOVERY_SCOPE}
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
