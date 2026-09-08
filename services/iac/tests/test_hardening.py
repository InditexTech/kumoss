# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Tests for the hardening backport: plan-file injection prevention,
subprocess timeout, EngineTimeoutError → 504, StarletteHTTPException
handler, and job-ID logging context."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from src.config import Config
from src import main as service_main
from src.models import PlanRequest

from .test_api import _client_with, _poll_until_terminal
from src.engine import (
    EngineTimeoutError,
    _plan_file_arg,
    set_timeout,
)


# -- Plan-file injection prevention --


def test_plan_file_arg_anchors_with_dot_slash() -> None:
    assert _plan_file_arg("foo.plan") == "./foo.plan"
    assert _plan_file_arg("abc123.plan") == "./abc123.plan"
    # Contract-valid names that would otherwise be parsed as flags.
    assert _plan_file_arg("-destroy") == "./-destroy"
    assert _plan_file_arg("-input=true") == "./-input=true"


@pytest.mark.parametrize(
    "bad_name", ["", "a/b", "a\\b", "../x", "with space", "x=y", "x" * 129]
)
def test_plan_file_regex_rejects_non_filename_chars(bad_name: str) -> None:
    """Only the contract's pattern is enforced: single segment, filename
    characters, 1..128 long. Path separators and other characters are
    rejected with a 422 at the schema level."""
    with pytest.raises(ValidationError):
        PlanRequest(workspace_path="/tmp/ws", scope_id="sub-test", plan_file=bad_name)


@pytest.mark.parametrize(
    "name", ["abc.plan", "my_plan_01.tfplan", "A1", "-destroy", ".hidden", "x" * 128]
)
def test_plan_file_regex_accepts_every_contract_valid_name(name: str) -> None:
    """No check stricter than the contract's: leading `-`/`.` are valid
    (the `./` anchoring keeps them from being flags) so Schemathesis
    conformance gets the 202 the contract promises."""
    req = PlanRequest(workspace_path="/tmp/ws", scope_id="sub-test", plan_file=name)
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
                json={"workspace_path": str(workspace), "scope_id": "sub-test"},
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


# -- oversized single line does not crash the job or orphan the process --


@pytest.mark.asyncio
async def test_oversized_line_is_captured_and_process_reaped(tmp_path: Path) -> None:
    """A single stdout line larger than the 10 MB StreamReader limit used to
    surface as ``ValueError`` from ``readline()`` and leave the engine
    process running. The output is the job result, so it must be captured
    in full; only the debug log is allowed to skip it."""
    from src.engine import _BUFFER_LIMIT, _run

    size = _BUFFER_LIMIT + 1_000_000
    script = (
        f"head -c {size} /dev/zero | tr '\\0' a; "
        "printf '\\nafter\\n'; "
        "echo err >&2; "
        "exit 3"
    )
    result = await _run("sh", ["-c", script], tmp_path)

    assert result.exit_code == 3
    assert result.ok is False
    assert len(result.stdout) == size + len("\nafter\n")
    assert result.stdout.startswith("a" * 1000)
    assert result.stdout.endswith("\nafter\n")
    assert result.stderr == "err\n"


@pytest.mark.asyncio
async def test_oversized_line_on_stderr_is_captured(tmp_path: Path) -> None:
    from src.engine import _BUFFER_LIMIT, _run

    size = _BUFFER_LIMIT + 1
    script = f"head -c {size} /dev/zero | tr '\\0' b >&2; echo ok"
    result = await _run("sh", ["-c", script], tmp_path)

    assert result.ok is True
    assert result.stdout == "ok\n"
    assert len(result.stderr) == size


# -- Startup cloud login is all-or-nothing --


def test_startup_aborts_when_a_configured_cloud_login_fails() -> None:
    """Every provider with complete credentials is logged into at startup;
    if any of them fails the service must not come up (a half-authenticated
    service would fail jobs later with confusing engine errors)."""
    from src import cloud_cli

    service_main.config = Config(
        expected_token="",
        iac_binary="sh",
        azure_client_id="az-id",
        azure_client_secret="az-secret",
        azure_tenant_id="az-tenant",
        google_credentials='{"type": "service_account"}',
    )
    original = cloud_cli._last_login
    cloud_cli._last_login = 0.0
    try:
        with (
            patch(
                "src.cloud_cli._az_login_sp",
                new_callable=AsyncMock,
                side_effect=RuntimeError("Azure login failed: bad secret"),
            ),
            patch("src.cloud_cli._gcloud_auth", new_callable=AsyncMock) as gcloud,
            pytest.raises(RuntimeError, match="Cloud login failed for: Azure"),
        ):
            with TestClient(service_main.app):
                pass
        gcloud.assert_awaited_once()  # GCP was still attempted
    finally:
        cloud_cli._last_login = original


# -- AssumeRole failures for non-AWS scopes are non-fatal --


@pytest.mark.parametrize(
    "failure",
    [
        RuntimeError("AWS AssumeRole failed for arn:...: AccessDenied"),
        FileNotFoundError("aws"),  # CLI not installed
    ],
    ids=["sts-denied", "cli-missing"],
)
def test_assume_role_failure_does_not_fail_non_aws_job(
    failure: Exception, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cross-cloud plans are not supported: with AWS keys and a role name
    configured, an Azure/GCP scope_id still triggers an AssumeRole attempt
    that can only fail. That failure must be swallowed and the job must run
    with the scope injected for the provider it actually targets."""
    from src.engine import CommandResult

    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIA-test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "secret-test")
    ok = CommandResult(ok=True, stdout="", stderr="", exit_code=0)

    with _client_with(
        azure_client_id="az-id",
        azure_client_secret="az-secret",
        azure_tenant_id="az-tenant",
        aws_terraform_role_name="role/nebula",
    ) as client:
        with (
            patch("src.cloud_cli.ensure_cloud_login", new_callable=AsyncMock),
            patch(
                "src.cloud_cli.aws_assume_role",
                new_callable=AsyncMock,
                side_effect=failure,
            ) as assume,
            patch("src.engine.init", new_callable=AsyncMock, return_value=ok) as init,
        ):
            response = client.post(
                "/v1/init",
                json={"workspace_path": str(workspace), "scope_id": "sub-uuid-1"},
            )
            assert response.status_code == 202
            body = _poll_until_terminal(client, response.json()["job_id"])

    assert body["status"] == "succeeded", body
    assume.assert_awaited_once_with("sub-uuid-1", "role/nebula")
    env = init.await_args.kwargs["env"]
    assert env["ARM_SUBSCRIPTION_ID"] == "sub-uuid-1"
    assert "AWS_SESSION_TOKEN" not in env  # nothing assumed
