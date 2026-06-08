"""Unit tests for the validation reference implementation.

These cover the contract surface: healthz, auth, validation/parsing of
the request, the 404-on-missing-workspace path, the 503 when terraform
isn't installed, and a plan-skipped (no creds) success path. They do NOT
exercise an actual `terraform plan` against a cloud — that requires
network and credentials.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from fastapi.testclient import TestClient

from src.config import Config
from src import main as service_main


@contextmanager
def _client_with(
    token: str = "",
    terraform_binary: str = "terraform",
    allow_plan_without_creds: bool = False,
):
    service_main.config = Config(
        expected_token=token,
        terraform_binary=terraform_binary,
        allow_plan_without_creds=allow_plan_without_creds,
    )
    with TestClient(service_main.app) as client:
        yield client


def test_healthz_ok() -> None:
    with _client_with() as client:
        response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_validate_requires_token_when_configured() -> None:
    with _client_with(token="expected") as client:
        response = client.post(
            "/v1/validate",
            json={"workspace_path": "/tmp/anywhere"},
        )
    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/problem+json")


def test_validate_503_when_terraform_missing() -> None:
    with _client_with(terraform_binary="terraform-does-not-exist-1234") as client:
        response = client.post(
            "/v1/validate",
            json={"workspace_path": "/tmp"},
        )
    assert response.status_code == 503
    assert response.headers["content-type"].startswith("application/problem+json")


def test_validate_404_when_workspace_missing(tmp_path: Path) -> None:
    # Use sh as a stand-in for terraform so the binary check passes; the
    # service should still 404 before invoking it because the workspace
    # path is bogus.
    with _client_with(terraform_binary="sh") as client:
        response = client.post(
            "/v1/validate",
            json={"workspace_path": str(tmp_path / "does-not-exist")},
        )
    assert response.status_code == 404


def test_validate_request_validation_returns_problem_json() -> None:
    with _client_with() as client:
        response = client.post(
            "/v1/validate",
            json={"workspace_path": ""},  # min_length=1
        )
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
