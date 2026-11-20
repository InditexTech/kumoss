# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Contract-level tests for the mapping reference implementation."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from fastapi.testclient import TestClient

from src import main as service_main
from src.config import Config

PREFIX = "https://github.com/MySuperOrg/"


@contextmanager
def _client_with(token: str = "", prefix: str = PREFIX) -> Generator[TestClient]:
    service_main.config = Config(expected_token=token, prefix_identifier=prefix)
    with TestClient(service_main.app) as client:
        yield client


def test_healthz_ok() -> None:
    with _client_with() as client:
        response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_bare_name_resolves_against_the_prefix() -> None:
    with _client_with() as client:
        response = client.post("/v1/resolve", json={"identifier": "foo"})
    assert response.status_code == 200
    assert response.json() == {
        "repo_url": "https://github.com/MySuperOrg/foo.git",
        "identifier": "foo",
    }


def test_https_url_passes_through_unchanged() -> None:
    url = "HTTPS://github.com/me/my-iac.git"
    with _client_with() as client:
        response = client.post("/v1/resolve", json={"identifier": url})
    assert response.status_code == 200
    assert response.json() == {"repo_url": url, "identifier": url}


def test_https_url_with_surrounding_spaces_is_stripped() -> None:
    url = "https://github.com/org/repo.git"
    with _client_with() as client:
        response = client.post("/v1/resolve", json={"identifier": f" {url} "})
    assert response.status_code == 200
    assert response.json() == {"repo_url": url, "identifier": f" {url} "}


def test_identifier_is_echoed_verbatim() -> None:
    with _client_with() as client:
        response = client.post("/v1/resolve", json={"identifier": " foo "})
    assert response.status_code == 200
    assert response.json()["identifier"] == " foo "


def test_bare_name_without_prefix_is_404_naming_the_setting() -> None:
    with _client_with(prefix="") as client:
        response = client.post("/v1/resolve", json={"identifier": "foo"})
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    assert "MAPPING_PREFIX_IDENTIFIER" in response.json()["detail"]


def test_unresolvable_identifier_is_404() -> None:
    for identifier in ("team/foo", "git@github.com:me/repo.git", "http://x/y.git"):
        with _client_with() as client:
            response = client.post("/v1/resolve", json={"identifier": identifier})
        assert response.status_code == 404, identifier
        assert response.headers["content-type"].startswith("application/problem+json")


def test_pre_2_0_terraform_provider_is_rejected() -> None:
    with _client_with() as client:
        response = client.post(
            "/v1/resolve", json={"identifier": "foo", "terraform_provider": "azurerm"}
        )
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")


def test_malformed_json_is_400() -> None:
    with _client_with() as client:
        response = client.post(
            "/v1/resolve",
            content=b"{not json",
            headers={"Content-Type": "application/json"},
        )
    assert response.status_code == 400
    assert response.headers["content-type"].startswith("application/problem+json")


def test_does_not_truncate_long_identifiers() -> None:
    long_identifier = "https://github.com/me/" + "a" * 500
    with _client_with() as client:
        response = client.post("/v1/resolve", json={"identifier": long_identifier})
    assert response.status_code == 200
    assert response.json()["identifier"] == long_identifier


def test_requires_token_when_configured() -> None:
    with _client_with(token="expected") as client:
        response = client.post("/v1/resolve", json={"identifier": "foo"})
    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_rejects_wrong_token() -> None:
    with _client_with(token="expected") as client:
        response = client.post(
            "/v1/resolve",
            headers={"Authorization": "Bearer nope"},
            json={"identifier": "foo"},
        )
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_accepts_right_token() -> None:
    with _client_with(token="expected") as client:
        response = client.post(
            "/v1/resolve",
            headers={"Authorization": "Bearer expected"},
            json={"identifier": "foo"},
        )
    assert response.status_code == 200


def test_validation_error_returns_problem_json() -> None:
    with _client_with() as client:
        response = client.post("/v1/resolve", json={"identifier": ""})
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
