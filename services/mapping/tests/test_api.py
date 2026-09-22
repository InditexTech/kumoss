# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the mapping reference implementation."""

from __future__ import annotations

from contextlib import contextmanager

from fastapi.testclient import TestClient

from src.config import Config
from src import main as service_main


@contextmanager
def _client_with(token: str = ""):
    service_main.config = Config(expected_token=token)
    with TestClient(service_main.app) as client:
        yield client


def test_healthz_ok() -> None:
    with _client_with() as client:
        response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_resolve_identity_returns_input() -> None:
    with _client_with() as client:
        response = client.post(
            "/v1/resolve",
            json={"identifier": "https://github.com/me/my-iac.git"},
        )
    assert response.status_code == 200
    assert response.json() == {
        "repo_url": "https://github.com/me/my-iac.git",
        "identifier": "https://github.com/me/my-iac.git",
        "terraform_provider": None,
        "scope_id": None,
    }


def test_resolve_echoes_terraform_provider_when_sent() -> None:
    with _client_with() as client:
        response = client.post(
            "/v1/resolve",
            json={"identifier": "my-project", "terraform_provider": "azure"},
        )
    assert response.status_code == 200
    assert response.json() == {
        "repo_url": "my-project",
        "identifier": "my-project",
        "terraform_provider": "azure",
        "scope_id": None,
    }


def test_resolve_never_guesses_a_provider() -> None:
    # An Azure DevOps URL says where the repo is hosted, not where it
    # deploys. The identity impl declines to conflate the two.
    with _client_with() as client:
        response = client.post(
            "/v1/resolve",
            json={"identifier": "https://dev.azure.com/org/proj/_git/iac"},
        )
    assert response.status_code == 200
    assert response.json()["terraform_provider"] is None


def test_resolve_scope_is_always_null() -> None:
    with _client_with() as client:
        response = client.post(
            "/v1/resolve",
            json={"identifier": "my-project", "terraform_provider": "gcp"},
        )
    assert response.status_code == 200
    assert response.json()["scope_id"] is None


def test_resolve_accepts_explicit_null_provider() -> None:
    with _client_with() as client:
        response = client.post(
            "/v1/resolve",
            json={"identifier": "my-project", "terraform_provider": None},
        )
    assert response.status_code == 200
    assert response.json()["terraform_provider"] is None


def test_resolve_rejects_provider_outside_the_enum() -> None:
    # `azurerm` is the Terraform registry name, not the core's vocabulary.
    with _client_with() as client:
        response = client.post(
            "/v1/resolve",
            json={"identifier": "my-project", "terraform_provider": "azurerm"},
        )
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")


def test_resolve_rejects_unknown_fields() -> None:
    # `cloud` and `environment` are gone; additionalProperties: false.
    with _client_with() as client:
        response = client.post(
            "/v1/resolve",
            json={"identifier": "my-project", "cloud": "azure"},
        )
    assert response.status_code == 422


def test_resolve_does_not_truncate_long_identifiers() -> None:
    # `identifier` shares the request's 1024-char cap, so the response no
    # longer silently mangles a long input the way `project[:128]` did.
    long_identifier = "https://github.com/me/" + "a" * 500
    with _client_with() as client:
        response = client.post(
            "/v1/resolve",
            json={"identifier": long_identifier},
        )
    assert response.status_code == 200
    assert response.json()["identifier"] == long_identifier


def test_resolve_requires_token_when_configured() -> None:
    with _client_with(token="expected") as client:
        response = client.post("/v1/resolve", json={"identifier": "x"})
    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_resolve_rejects_wrong_token() -> None:
    with _client_with(token="expected") as client:
        response = client.post(
            "/v1/resolve",
            headers={"Authorization": "Bearer nope"},
            json={"identifier": "x"},
        )
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_resolve_validation_error_returns_problem_json() -> None:
    with _client_with() as client:
        response = client.post(
            "/v1/resolve",
            json={"identifier": ""},  # min_length=1
        )
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
