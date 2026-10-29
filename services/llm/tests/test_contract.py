# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""The hand-written models match contracts/openapi/llm.v1.yaml.

Skipped when the contract is not reachable (the service directory
mounted on its own); run from a full checkout to include it.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from src import models

CONTRACT = Path(__file__).resolve().parents[3] / "contracts" / "openapi" / "llm.v1.yaml"

pytestmark = pytest.mark.skipif(not CONTRACT.is_file(), reason="contract not mounted")


@pytest.fixture(scope="module")
def spec() -> dict:
    return yaml.safe_load(CONTRACT.read_text())


@pytest.mark.parametrize(
    "name",
    [
        "CompletionRequest",
        "CompletionResponse",
        "ToolCall",
        "SearchRequest",
        "SearchResponse",
        "SearchResult",
        "Health",
    ],
)
def test_schema_fields_match_the_model(spec: dict, name: str) -> None:
    schema = spec["components"]["schemas"][name]
    model = getattr(models, name)
    assert set(schema["properties"]) == set(model.model_fields)
    assert set(schema.get("required", [])) == {
        field for field, info in model.model_fields.items() if info.is_required()
    }
    assert schema["additionalProperties"] is False
    assert model.model_config.get("extra") == "forbid"


def test_paths_and_security(spec: dict) -> None:
    assert set(spec["paths"]) == {"/v1/completions", "/v1/search", "/v1/healthz"}
    for path in ("/v1/completions", "/v1/search"):
        assert spec["paths"][path]["post"]["security"] == [{"bearerAuth": []}]
    assert "security" not in spec["paths"]["/v1/healthz"]["get"]
