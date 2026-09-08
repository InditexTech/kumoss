# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Tests for the hardening backport: plan-file injection prevention,
subprocess timeout, EngineTimeoutError → 504, StarletteHTTPException
handler, and job-ID logging context."""

from __future__ import annotations

import time
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from src.config import Config
from src.jobs import JobRegistry, WorkspaceQueue
from src import main as service_main
from src.models import PlanRequest
from src.engine import (
    EngineTimeoutError,
    _plan_file_arg,
    set_timeout,
)


@contextmanager
def _client_with(
    token: str = "",
    iac_binary: str = "sh",
    job_ttl: int = 3600,
):
    service_main.config = Config(
        expected_token=token,
        iac_binary=iac_binary,
        job_ttl=job_ttl,
    )
    service_main.workspace_queue = WorkspaceQueue()
    service_main.jobs = JobRegistry(
        ttl_seconds=job_ttl, workspace_queue=service_main.workspace_queue
    )
    with TestClient(service_main.app) as client:
        yield client


def _poll_until_terminal(
    client: TestClient,
    job_id: str,
    deadline: float = 5.0,
) -> dict:
    t0 = time.monotonic()
    while time.monotonic() - t0 < deadline:
        response = client.get(f"/v1/jobs/{job_id}")
        assert response.status_code == 200, response.text
        body = response.json()
        if body["status"] in ("succeeded", "failed"):
            return body
        time.sleep(0.01)
    raise AssertionError(f"job {job_id} did not reach a terminal state")


# -- Plan-file injection prevention --


def test_plan_file_arg_anchors_with_dot_slash() -> None:
    assert _plan_file_arg("foo.plan") == "./foo.plan"
    assert _plan_file_arg("abc123.plan") == "./abc123.plan"


@pytest.mark.parametrize("bad_name", ["-destroy", "-input=true", ".hidden"])
def test_plan_file_regex_rejects_leading_special_chars(bad_name: str) -> None:
    with pytest.raises(ValidationError):
        PlanRequest(
            workspace_path="/tmp/ws",
            plan_file=bad_name,
        )


def test_plan_file_regex_accepts_valid_names() -> None:
    for name in ["abc.plan", "my_plan_01.tfplan", "A1"]:
        req = PlanRequest(workspace_path="/tmp/ws", plan_file=name)
        assert req.plan_file == name


# -- Subprocess timeout --


def test_terraform_timeout_error_fails_job_504(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()

    with _client_with() as client:
        with patch(
            "src.engine.init",
            new_callable=AsyncMock,
            side_effect=EngineTimeoutError("timed out after 2700s"),
        ):
            response = client.post(
                "/v1/init",
                json={"workspace_path": str(workspace)},
            )
            assert response.status_code == 202
            body = _poll_until_terminal(client, response.json()["job_id"])
    assert body["status"] == "failed"
    assert body["error"]["status"] == 504
    assert "timed out" in body["error"]["detail"]


def test_set_timeout_zero_disables() -> None:
    set_timeout(0)
    from src.engine import _timeout
    assert _timeout is None


def test_set_timeout_negative_disables() -> None:
    set_timeout(-1)
    from src.engine import _timeout
    assert _timeout is None


def test_set_timeout_positive_sets_value() -> None:
    set_timeout(120)
    from src.engine import _timeout
    assert _timeout == 120
    set_timeout(0)


# -- Starlette exception handler --


def test_method_not_allowed_returns_problem_json() -> None:
    with _client_with() as client:
        response = client.get("/v1/init")
    assert response.status_code == 405
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["status"] == 405
    assert body["title"] == "Method Not Allowed"


def test_starlette_404_returns_problem_json() -> None:
    with _client_with() as client:
        response = client.get("/nonexistent/path")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")


# -- engine wrapper is binary-agnostic --


@pytest.mark.asyncio
async def test_timeout_error_names_the_configured_binary(tmp_path: Path) -> None:
    """The timeout message must name the engine actually invoked (tofu,
    terraform, ...) rather than hard-coding 'terraform'."""
    from src.engine import _run

    set_timeout(1)
    try:
        with pytest.raises(EngineTimeoutError) as excinfo:
            await _run("sh", ["-c", "exec sleep 5"], tmp_path)
    finally:
        set_timeout(0)
    message = str(excinfo.value)
    assert message.startswith("sh -c timed out")
    assert "terraform" not in message
