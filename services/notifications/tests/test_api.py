# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the notifications reference implementation.

Cover the contract-visible behaviors: healthz, auth (missing/wrong/right
token), validation errors, the 502 paths (Slack HTTP error, Slack
unreachable) and the happy path, all mocked at the Slack boundary.
"""

from __future__ import annotations

from contextlib import contextmanager

import httpx
import respx
from fastapi.testclient import TestClient
from httpx import Response

from src.config import Config
from src import main as service_main


@contextmanager
def _client_with(token: str = "", webhook: str = "https://hooks.slack.example/x"):
    """Yield a TestClient with the service config swapped in.

    The TestClient is entered as a context manager so the FastAPI lifespan
    (which sets up the shared httpx.AsyncClient) actually runs.
    """
    service_main.config = Config(slack_webhook_url=webhook, expected_token=token)
    with TestClient(service_main.app) as client:
        yield client


def test_healthz_ok() -> None:
    with _client_with() as client:
        response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_notify_requires_token_when_configured() -> None:
    with _client_with(token="expected-token") as client:
        response = client.post(
            "/v1/notify",
            json={
                "kind": "system.info",
                "severity": "info",
                "subject": "hi",
                "body": "hello",
            },
        )
    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_notify_rejects_wrong_token() -> None:
    with _client_with(token="expected-token") as client:
        response = client.post(
            "/v1/notify",
            headers={"Authorization": "Bearer wrong-token"},
            json={
                "kind": "system.info",
                "severity": "info",
                "subject": "hi",
                "body": "hello",
            },
        )
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_notify_validation_error_returns_problem_json() -> None:
    with _client_with(token="") as client:
        response = client.post(
            "/v1/notify",
            json={"kind": "x", "severity": "wat", "subject": "s", "body": "b"},
        )
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")


def test_notify_happy_path_calls_slack() -> None:
    webhook = "https://hooks.slack.example/T0/B0/secret"
    with _client_with(token="", webhook=webhook) as client:
        with respx.mock(assert_all_called=True) as router:
            slack = router.post(webhook).mock(return_value=Response(200, text="ok"))
            response = client.post(
                "/v1/notify",
                json={
                    "kind": "iac.terraform.plan_completed",
                    "severity": "info",
                    "subject": "Plan complete",
                    "body": "All clear.",
                    "audience": ["#ops"],
                    "links": [{"label": "Plan", "url": "https://example.com/p"}],
                },
            )
            assert slack.called

    assert response.status_code == 202
    payload = response.json()
    assert "delivery_id" in payload


def test_notify_accepts_correct_token() -> None:
    webhook = "https://hooks.slack.example/T0/B0/secret"
    with _client_with(token="expected-token", webhook=webhook) as client:
        with respx.mock(assert_all_called=True) as router:
            router.post(webhook).mock(return_value=Response(200, text="ok"))
            response = client.post(
                "/v1/notify",
                headers={"Authorization": "Bearer expected-token"},
                json={
                    "kind": "system.info",
                    "severity": "info",
                    "subject": "hi",
                    "body": "hello",
                },
            )
    assert response.status_code == 202


def test_notify_returns_502_when_slack_rejects_without_leaking_webhook() -> None:
    # The webhook URL is the Slack credential and httpx embeds it in every
    # error message, so the 502 problem carries a fixed title and no detail.
    webhook = "https://hooks.slack.example/T0/B0/SECRETPART"
    with _client_with(token="", webhook=webhook) as client:
        with respx.mock(assert_all_called=True) as router:
            router.post(webhook).mock(return_value=Response(404, text="no_service"))
            response = client.post(
                "/v1/notify",
                json={
                    "kind": "system.info",
                    "severity": "info",
                    "subject": "hi",
                    "body": "hello",
                },
            )
    assert response.status_code == 502
    assert response.headers["content-type"].startswith("application/problem+json")
    payload = response.json()
    assert payload["status"] == 502
    assert payload["title"] == "Downstream channel error"
    assert "detail" not in payload
    assert "no_service" not in response.text
    assert "SECRETPART" not in response.text
    assert "hooks.slack.example" not in response.text


def test_notify_returns_502_when_slack_unreachable_without_leaking_webhook() -> None:
    webhook = "https://hooks.slack.example/T0/B0/SECRETPART"
    with _client_with(token="", webhook=webhook) as client:
        with respx.mock(assert_all_called=True) as router:
            router.post(webhook).mock(side_effect=httpx.ConnectError("boom"))
            response = client.post(
                "/v1/notify",
                json={
                    "kind": "system.info",
                    "severity": "info",
                    "subject": "hi",
                    "body": "hello",
                },
            )
    assert response.status_code == 502
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["title"] == "Downstream channel error"
    assert "SECRETPART" not in response.text
    assert "hooks.slack.example" not in response.text
