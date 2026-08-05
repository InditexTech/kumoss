# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the IaC reference implementation.

These cover the contract surface: healthz, auth, request validation,
the 404-on-missing-workspace path, the 503 when terraform isn't
installed, the async job lifecycle (202 submit → poll to terminal),
per-workspace FIFO queueing, job expiry, and a plan-skipped (no creds)
success path. They do NOT exercise an actual `terraform plan` against
a cloud — that requires network and credentials.
"""

from __future__ import annotations

import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from src.config import Config
from src.jobs import JobRegistry, WorkspaceQueue
from src import main as service_main


@contextmanager
def _client_with(
    token: str = "",
    terraform_binary: str = "sh",
    allow_plan_without_creds: bool = False,
    job_ttl: int = 3600,
):
    # `sh` stands in for terraform so Config's fail-fast binary check
    # passes in terraform-less test environments; subprocess calls are
    # patched in every test that would reach them.
    service_main.config = Config(
        expected_token=token,
        terraform_binary=terraform_binary,
        allow_plan_without_creds=allow_plan_without_creds,
        job_ttl=job_ttl,
    )
    # Fresh queue/registry per test so job records don't leak across tests.
    service_main.workspace_queue = WorkspaceQueue()
    service_main.jobs = JobRegistry(
        ttl_seconds=job_ttl, workspace_queue=service_main.workspace_queue
    )
    with TestClient(service_main.app) as client:
        yield client


def _poll_until_terminal(
    client: TestClient,
    job_id: str,
    headers: dict[str, str] | None = None,
    deadline: float = 5.0,
) -> dict:
    """Poll GET /v1/jobs/{job_id} until succeeded/failed.

    Must be called inside the ``TestClient`` context manager: the job
    task runs on the client's portal event loop, which dies when the
    ``with`` block exits.
    """
    t0 = time.monotonic()
    while time.monotonic() - t0 < deadline:
        response = client.get(f"/v1/jobs/{job_id}", headers=headers or {})
        assert response.status_code == 200, response.text
        body = response.json()
        if body["status"] in ("succeeded", "failed"):
            return body
        time.sleep(0.01)
    raise AssertionError(f"job {job_id} did not reach a terminal state")


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
    with _client_with() as client:
        with patch("src.main.terraform_available", return_value=False):
            response = client.post(
                "/v1/validate",
                json={"workspace_path": "/tmp"},
            )
    assert response.status_code == 503
    assert response.headers["content-type"].startswith("application/problem+json")


def test_validate_404_when_workspace_missing(tmp_path: Path) -> None:
    # The service should 404 before enqueueing anything because the
    # workspace path is bogus.
    with _client_with() as client:
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


def test_validate_rejects_empty_target_string() -> None:
    with _client_with() as client:
        response = client.post(
            "/v1/validate",
            json={"workspace_path": "/tmp", "targets": [""]},
        )
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")


def test_validate_submit_returns_202_with_location(tmp_path: Path) -> None:
    """Submission returns 202 + JobAccepted and a Location header."""
    from src.terraform import CommandResult

    workspace = tmp_path / "ws"
    workspace.mkdir()

    init_failed = CommandResult(ok=False, stdout="", stderr="nope")
    with _client_with() as client:
        with patch(
            "src.terraform.init", new_callable=AsyncMock, return_value=init_failed
        ):
            response = client.post(
                "/v1/validate",
                json={"workspace_path": str(workspace)},
            )
            assert response.status_code == 202
            body = response.json()
            assert body["status"] == "queued"
            job_id = body["job_id"]
            assert response.headers["location"] == f"/v1/jobs/{job_id}"
            _poll_until_terminal(client, job_id)


def test_jobs_fifo_same_workspace(tmp_path: Path) -> None:
    """Two jobs on the same workspace queue FIFO: the second stays
    `queued` while the first runs, and starts only after it finishes."""
    import asyncio
    import threading
    from datetime import datetime

    from src.terraform import CommandResult

    workspace = tmp_path / "ws"
    workspace.mkdir()

    release = threading.Event()

    async def blocked_init(*args, **kwargs):
        while not release.is_set():
            await asyncio.sleep(0.005)
        # Fail init so the pipeline short-circuits to a false-flag result.
        return CommandResult(ok=False, stdout="", stderr="init stubbed")

    with _client_with() as client:
        with patch("src.terraform.init", side_effect=blocked_init):
            first = client.post(
                "/v1/validate", json={"workspace_path": str(workspace)}
            ).json()["job_id"]
            second = client.post(
                "/v1/validate", json={"workspace_path": str(workspace)}
            ).json()["job_id"]

            # Wait for the first job to be running, then check the second
            # is queued behind it (not rejected, not running).
            t0 = time.monotonic()
            while time.monotonic() - t0 < 5.0:
                if client.get(f"/v1/jobs/{first}").json()["status"] == "running":
                    break
                time.sleep(0.01)
            else:
                raise AssertionError("first job never started running")
            assert client.get(f"/v1/jobs/{second}").json()["status"] == "queued"

            release.set()
            first_body = _poll_until_terminal(client, first)
            second_body = _poll_until_terminal(client, second)

    assert first_body["status"] == "succeeded"
    assert second_body["status"] == "succeeded"
    assert first_body["result"]["validation"] is False
    # FIFO: the second job started only after the first finished.
    assert datetime.fromisoformat(second_body["started_at"]) >= datetime.fromisoformat(
        first_body["finished_at"]
    )


def test_validate_init_failure_succeeds_with_validation_false(tmp_path: Path) -> None:
    """`terraform init` failure is a Terraform-level failure: the job
    ends `succeeded` with validation=false and the CLI stderr in the
    result's feedback — not a `failed` job."""
    from src.terraform import CommandResult

    workspace = tmp_path / "ws"
    workspace.mkdir()

    init_failed = CommandResult(
        ok=False, stdout="", stderr="Error: backend init failed"
    )
    with _client_with() as client:
        with patch(
            "src.terraform.init", new_callable=AsyncMock, return_value=init_failed
        ):
            response = client.post(
                "/v1/validate",
                json={"workspace_path": str(workspace), "targets": ["module.db"]},
            )
            assert response.status_code == 202
            body = _poll_until_terminal(client, response.json()["job_id"])
    assert body["status"] == "succeeded"
    assert body["kind"] == "validate"
    assert body["error"] is None
    result = body["result"]
    assert result["validation"] is False
    assert "backend init failed" in result["feedback"]
    assert result["terraform_plan"] == ""
    assert result["terraform_targets"] == ["module.db"]


def test_apply_init_failure_succeeds_with_success_false(tmp_path: Path) -> None:
    from src.terraform import CommandResult

    workspace = tmp_path / "ws"
    workspace.mkdir()

    init_failed = CommandResult(
        ok=False, stdout="", stderr="Error: backend init failed"
    )
    with _client_with() as client:
        with patch(
            "src.terraform.init", new_callable=AsyncMock, return_value=init_failed
        ):
            response = client.post(
                "/v1/apply",
                json={"workspace_path": str(workspace)},
            )
            assert response.status_code == 202
            body = _poll_until_terminal(client, response.json()["job_id"])
    assert body["status"] == "succeeded"
    assert body["kind"] == "apply"
    result = body["result"]
    assert result["success"] is False
    assert "backend init failed" in result["feedback"]
    assert result["terraform_output"] == ""


def test_import_init_failure_succeeds_with_success_false(tmp_path: Path) -> None:
    from src.terraform import CommandResult

    workspace = tmp_path / "ws"
    workspace.mkdir()

    init_failed = CommandResult(
        ok=False, stdout="", stderr="Error: backend init failed"
    )
    with _client_with() as client:
        with patch(
            "src.terraform.init", new_callable=AsyncMock, return_value=init_failed
        ):
            response = client.post(
                "/v1/import",
                json={
                    "workspace_path": str(workspace),
                    "address": "azurerm_resource_group.main",
                    "resource_id": "/subscriptions/x/resourceGroups/y",
                },
            )
            assert response.status_code == 202
            body = _poll_until_terminal(client, response.json()["job_id"])
    assert body["status"] == "succeeded"
    assert body["kind"] == "import"
    result = body["result"]
    assert result["success"] is False
    assert "backend init failed" in result["feedback"]


def test_validate_plan_skipped_without_creds(tmp_path: Path) -> None:
    """When init+validate pass but no cloud credentials are configured,
    the job succeeds with validation=true and an explanatory feedback,
    without running `terraform plan`."""
    from src.terraform import CommandResult

    workspace = tmp_path / "ws"
    workspace.mkdir()

    ok = CommandResult(ok=True, stdout="", stderr="")
    with _client_with() as client:
        with (
            patch("src.terraform.init", new_callable=AsyncMock, return_value=ok),
            patch("src.terraform.validate", new_callable=AsyncMock, return_value=ok),
            patch("src.main.have_cloud_credentials", return_value=False),
            patch("src.terraform.plan", new_callable=AsyncMock) as plan_mock,
        ):
            response = client.post(
                "/v1/validate",
                json={"workspace_path": str(workspace)},
            )
            assert response.status_code == 202
            body = _poll_until_terminal(client, response.json()["job_id"])
    assert body["status"] == "succeeded"
    result = body["result"]
    assert result["validation"] is True
    assert "plan skipped" in result["feedback"]
    plan_mock.assert_not_called()


def test_unexpected_error_fails_job_500(tmp_path: Path) -> None:
    """An unexpected exception in the pipeline is a service-level fault:
    the job ends `failed` with a 500 problem."""
    workspace = tmp_path / "ws"
    workspace.mkdir()

    with _client_with() as client:
        with patch(
            "src.terraform.init",
            new_callable=AsyncMock,
            side_effect=RuntimeError("subprocess exploded"),
        ):
            response = client.post(
                "/v1/validate",
                json={"workspace_path": str(workspace)},
            )
            assert response.status_code == 202
            body = _poll_until_terminal(client, response.json()["job_id"])
    assert body["status"] == "failed"
    assert body["result"] is None
    assert body["error"]["status"] == 500
    assert "subprocess exploded" in body["error"]["detail"]


def test_get_job_404_when_unknown() -> None:
    with _client_with() as client:
        response = client.get(f"/v1/jobs/{uuid.uuid4()}")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")


def test_get_job_422_when_malformed_id() -> None:
    with _client_with() as client:
        response = client.get("/v1/jobs/not-a-uuid")
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")


def test_get_job_requires_token_when_configured() -> None:
    with _client_with(token="expected") as client:
        response = client.get(f"/v1/jobs/{uuid.uuid4()}")
    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/problem+json")


def test_job_expires_after_ttl(tmp_path: Path) -> None:
    """With job_ttl=0, a terminal job is swept on the next poll → 404."""
    from src.terraform import CommandResult

    workspace = tmp_path / "ws"
    workspace.mkdir()

    init_failed = CommandResult(ok=False, stdout="", stderr="nope")
    with _client_with(job_ttl=0) as client:
        with patch(
            "src.terraform.init", new_callable=AsyncMock, return_value=init_failed
        ):
            response = client.post(
                "/v1/validate",
                json={"workspace_path": str(workspace)},
            )
            assert response.status_code == 202
            job_id = response.json()["job_id"]
            # The job may still be observed while queued/running; once it
            # reaches a terminal state it expires immediately (ttl=0) and
            # the next poll sweeps it away.
            t0 = time.monotonic()
            while time.monotonic() - t0 < 5.0:
                poll = client.get(f"/v1/jobs/{job_id}")
                if poll.status_code == 404:
                    break
                assert poll.json()["status"] in ("queued", "running", "succeeded")
                time.sleep(0.01)
            else:
                raise AssertionError("terminal job was never swept")


def test_validate_accepts_scope_id() -> None:
    """scope_id is accepted without 422 (extra='forbid' would reject unknown fields)."""
    with _client_with() as client:
        response = client.post(
            "/v1/validate",
            json={
                "workspace_path": "/tmp/does-not-exist",
                "scope_id": "sub-uuid-1234",
            },
        )
    assert response.status_code == 404


def test_apply_accepts_scope_id() -> None:
    with _client_with() as client:
        response = client.post(
            "/v1/apply",
            json={
                "workspace_path": "/tmp/does-not-exist",
                "scope_id": "sub-uuid-1234",
            },
        )
    assert response.status_code == 404


def test_import_accepts_scope_id() -> None:
    with _client_with() as client:
        response = client.post(
            "/v1/import",
            json={
                "workspace_path": "/tmp/does-not-exist",
                "scope_id": "sub-uuid-1234",
                "address": "azurerm_resource_group.main",
                "resource_id": "/subscriptions/sub-1/resourceGroups/rg",
            },
        )
    assert response.status_code == 404
