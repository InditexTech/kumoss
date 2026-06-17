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
        "project": "https://github.com/me/my-iac.git",
        "branch": None,
        "path": None,
    }


def test_resolve_passes_through_optional_hints() -> None:
    with _client_with() as client:
        response = client.post(
            "/v1/resolve",
            json={
                "identifier": "my-project",
                "cloud": "azure",
                "environment": "dev",
            },
        )
    assert response.status_code == 200
    body = response.json()
    # Identity impl ignores hints; only the identifier shapes the response.
    assert body["repo_url"] == "my-project"
    assert body["project"] == "my-project"


def test_resolve_requires_token_when_configured() -> None:
    with _client_with(token="expected") as client:
        response = client.post("/v1/resolve", json={"identifier": "x"})
    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/problem+json")


def test_resolve_rejects_wrong_token() -> None:
    with _client_with(token="expected") as client:
        response = client.post(
            "/v1/resolve",
            headers={"Authorization": "Bearer nope"},
            json={"identifier": "x"},
        )
    assert response.status_code == 401


def test_resolve_validation_error_returns_problem_json() -> None:
    with _client_with() as client:
        response = client.post(
            "/v1/resolve",
            json={"identifier": ""},  # min_length=1
        )
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
