# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the authz reference implementation."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.config import Config
from src import main as service_main


@contextmanager
def _client_with(
    tmp_path: Path,
    token: str = "",
    root_admin_email: str = "",
    permissive: bool = True,
):
    role_store = tmp_path / "roles.json"
    service_main.config = Config(
        expected_token=token,
        role_store_path=str(role_store),
        root_admin_email=root_admin_email,
        permissive_check=permissive,
    )
    with TestClient(service_main.app) as client:
        yield client


def test_healthz_ok(tmp_path: Path) -> None:
    with _client_with(tmp_path) as client:
        response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_check_permissive_returns_true(tmp_path: Path) -> None:
    with _client_with(tmp_path) as client:
        response = client.post(
            "/v1/check",
            json={"cloud": "azure", "project": "anything"},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["authorized"] is True


def test_check_non_permissive_returns_false(tmp_path: Path) -> None:
    with _client_with(tmp_path, permissive=False) as client:
        response = client.post(
            "/v1/check",
            json={"cloud": "azure", "project": "anything"},
        )
    assert response.status_code == 200
    assert response.json()["authorized"] is False


@pytest.mark.parametrize(
    "headers",
    [
        pytest.param({}, id="no-authorization-header"),
        pytest.param({"Authorization": "Basic Zm9vOmJhcg=="}, id="wrong-scheme"),
        pytest.param({"Authorization": "Bearer nope"}, id="wrong-token"),
    ],
)
def test_check_requires_token(tmp_path: Path, headers: dict[str, str]) -> None:
    with _client_with(tmp_path, token="expected") as client:
        response = client.post(
            "/v1/check",
            json={"cloud": "azure", "project": "p"},
            headers=headers,
        )
    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_users_me_anonymous_when_no_header(tmp_path: Path) -> None:
    with _client_with(tmp_path) as client:
        response = client.get("/v1/users/me")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "anonymous"
    assert body["roles"] == []


def test_users_me_creates_record_on_first_call(tmp_path: Path) -> None:
    with _client_with(tmp_path) as client:
        response = client.get(
            "/v1/users/me",
            headers={"X-User-Id": "alice", "X-User-Email": "alice@example.com"},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "alice"
    assert body["email"] == "alice@example.com"
    assert body["roles"] == []
    # Persisted on disk
    role_store = tmp_path / "roles.json"
    assert role_store.exists()


def test_root_admin_bootstrap(tmp_path: Path) -> None:
    with _client_with(tmp_path, root_admin_email="root@example.com") as client:
        response = client.get(
            "/v1/users/me",
            headers={"X-User-Id": "root@example.com"},
        )
    assert response.status_code == 200
    assert "admin" in response.json()["roles"]


def test_list_roles_returns_catalogue(tmp_path: Path) -> None:
    with _client_with(tmp_path) as client:
        response = client.get("/v1/roles")
    assert response.status_code == 200
    names = {r["name"] for r in response.json()["roles"]}
    assert "admin" in names
    assert "user" in names


def test_list_users_requires_admin(tmp_path: Path) -> None:
    with _client_with(tmp_path) as client:
        response = client.get("/v1/users", headers={"X-User-Id": "alice"})
    assert response.status_code == 403


def test_assign_and_revoke_role_flow(tmp_path: Path) -> None:
    with _client_with(tmp_path, root_admin_email="root@example.com") as client:
        admin_headers = {"X-User-Id": "root@example.com"}
        # alice gets the user role
        response = client.post(
            "/v1/users/alice/roles",
            headers=admin_headers,
            json={"role": "user"},
        )
        assert response.status_code == 204
        # alice's record now exists with that role
        response = client.get("/v1/users/me", headers={"X-User-Id": "alice"})
        assert "user" in response.json()["roles"]
        # revoke
        response = client.delete("/v1/users/alice/roles/user", headers=admin_headers)
        assert response.status_code == 204
        response = client.get("/v1/users/me", headers={"X-User-Id": "alice"})
        assert "user" not in response.json()["roles"]


def test_assign_unknown_role_returns_404(tmp_path: Path) -> None:
    with _client_with(tmp_path, root_admin_email="root@example.com") as client:
        response = client.post(
            "/v1/users/alice/roles",
            headers={"X-User-Id": "root@example.com"},
            json={"role": "no-such-role"},
        )
    assert response.status_code == 404
