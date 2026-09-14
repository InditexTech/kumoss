# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the IaC reference implementation.

These cover the contract surface: healthz, auth, request validation
(including the `plan_file` path-traversal guard), the
404-on-missing-workspace path,
the async job lifecycle (202 submit → poll to terminal), the raw
{exit_code, stdout, stderr} pass-through for every operation, the 501
on the unimplemented import endpoints, per-workspace FIFO queueing, and
job expiry. They do NOT exercise an actual engine run against a cloud —
that requires network and credentials.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from src.config import Config
from src.jobs import JobRegistry, WorkspaceQueue
from src import main as service_main
from src.engine import CommandResult


# (endpoint, engine function to stub, extra request fields)
OPERATIONS: list[tuple[str, str, dict[str, str]]] = [
    ("/v1/init", "src.engine.init", {}),
    ("/v1/validate", "src.engine.validate", {}),
    ("/v1/plan", "src.engine.plan", {"plan_file": "x.plan"}),
    ("/v1/show", "src.engine.show_plan_json", {"plan_file": "x.plan"}),
    ("/v1/apply", "src.engine.apply", {"plan_file": "x.plan"}),
]

IMPORT_ENDPOINTS: list[str] = [
    "/v1/import",
    "/v1/import/state-resource-ids",
    "/v1/import/scope-resource-ids",
]


@contextmanager
def client_with(
    token: str = "",
    iac_binary: str = "sh",
    job_ttl: int = 3600,
) -> Generator[TestClient]:
    # `sh` stands in for the engine so Config's fail-fast binary check
    # passes in engine-less test environments; subprocess calls are
    # patched in every test that would reach them.
    service_main.config = Config(
        expected_token=token,
        iac_binary=iac_binary,
        job_ttl=job_ttl,
    )
    # Fresh queue/registry per test so job records don't leak across tests.
    service_main.workspace_queue = WorkspaceQueue()
    service_main.jobs = JobRegistry(
        ttl_seconds=job_ttl, workspace_queue=service_main.workspace_queue
    )
    with TestClient(service_main.app) as client:
        yield client


def poll_until_terminal(
    client: TestClient,
    job_id: str,
    deadline: float = 5.0,
) -> dict[str, Any]:
    """Poll GET /v1/jobs/{job_id} until succeeded/failed.

    Must be called inside the ``TestClient`` context manager: the job
    task runs on the client's portal event loop, which dies when the
    ``with`` block exits.
    """
    t0 = time.monotonic()
    while time.monotonic() - t0 < deadline:
        response = client.get(f"/v1/jobs/{job_id}")
        assert response.status_code == 200, response.text
        body: dict[str, Any] = response.json()
        if body["status"] in ("succeeded", "failed"):
            return body
        time.sleep(0.01)
    raise AssertionError(f"job {job_id} did not reach a terminal state")


def test_healthz_ok() -> None:
    with client_with() as client:
        response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_init_requires_token_when_configured() -> None:
    with client_with(token="expected") as client:
        response = client.post(
            "/v1/init",
            json={"workspace_path": "/tmp/anywhere"},
        )
    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/problem+json")


def test_init_404_when_workspace_missing(tmp_path: Path) -> None:
    # The service should 404 before enqueueing anything because the
    # workspace path is bogus.
    with client_with() as client:
        response = client.post(
            "/v1/init",
            json={"workspace_path": str(tmp_path / "does-not-exist")},
        )
    assert response.status_code == 404


def test_init_request_validation_returns_problem_json() -> None:
    with client_with() as client:
        response = client.post(
            "/v1/init",
            json={"workspace_path": ""},  # min_length=1
        )
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")


def test_plan_rejects_empty_target_string() -> None:
    with client_with() as client:
        response = client.post(
            "/v1/plan",
            json={"workspace_path": "/tmp", "targets": [""], "plan_file": "x.plan"},
        )
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")


@pytest.mark.parametrize("endpoint", ["/v1/plan", "/v1/show", "/v1/apply"])
def test_plan_file_traversal_rejected(endpoint: str) -> None:
    """`plan_file` lands in `-out` / `show` / `apply` argv: anything
    that isn't a single path segment must be rejected at the schema."""
    with client_with() as client:
        response = client.post(
            endpoint,
            json={"workspace_path": "/tmp", "plan_file": "../evil"},
        )
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")


def test_init_submit_returns_202_with_location(tmp_path: Path) -> None:
    """Submission returns 202 + JobAccepted and a Location header."""
    workspace = tmp_path / "ws"
    workspace.mkdir()

    init_failed = CommandResult(ok=False, stdout="", stderr="nope", exit_code=1)
    with client_with() as client:
        with patch("src.engine.init", new_callable=AsyncMock, return_value=init_failed):
            response = client.post(
                "/v1/init",
                json={"workspace_path": str(workspace)},
            )
            assert response.status_code == 202
            body: dict[str, Any] = response.json()
            assert body["status"] == "queued"
            job_id: str = body["job_id"]
            assert response.headers["location"] == f"/v1/jobs/{job_id}"
            _ = poll_until_terminal(client, job_id)


def test_jobs_fifo_same_workspace(tmp_path: Path) -> None:
    """Two jobs on the same workspace queue FIFO: the second stays
    `queued` while the first runs, and starts only after it finishes."""
    import asyncio
    import threading
    from datetime import datetime

    workspace = tmp_path / "ws"
    workspace.mkdir()

    release = threading.Event()

    async def blocked_init(*_args: object, **_kwargs: object) -> CommandResult:
        while not release.is_set():
            await asyncio.sleep(0.005)
        return CommandResult(ok=False, stdout="", stderr="init stubbed", exit_code=1)

    with client_with() as client:
        with patch("src.engine.init", side_effect=blocked_init):
            first: str = client.post(
                "/v1/init", json={"workspace_path": str(workspace)}
            ).json()["job_id"]
            second: str = client.post(
                "/v1/init", json={"workspace_path": str(workspace)}
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
            first_body = poll_until_terminal(client, first)
            second_body = poll_until_terminal(client, second)

    assert first_body["status"] == "succeeded"
    assert second_body["status"] == "succeeded"
    assert first_body["result"]["exit_code"] == 1
    # FIFO: the second job started only after the first finished.
    second_started: str = second_body["started_at"]
    first_finished: str = first_body["finished_at"]
    assert datetime.fromisoformat(second_started) >= datetime.fromisoformat(
        first_finished
    )


@pytest.mark.parametrize(("endpoint", "engine_target", "extra"), OPERATIONS)
def test_op_job_returns_raw_result_verbatim(
    endpoint: str, engine_target: str, extra: dict[str, str], tmp_path: Path
) -> None:
    """An engine-level failure is a `succeeded` job whose result is
    the raw {exit_code, stdout, stderr} — not a `failed` job, and not
    interpreted by the service."""
    workspace = tmp_path / "ws"
    workspace.mkdir()

    failed = CommandResult(
        ok=False, stdout="partial output", stderr="Error: it broke", exit_code=1
    )
    with client_with() as client:
        with patch(engine_target, new_callable=AsyncMock, return_value=failed):
            response = client.post(
                endpoint,
                json={"workspace_path": str(workspace), **extra},
            )
            assert response.status_code == 202
            accepted: dict[str, str] = response.json()
            body = poll_until_terminal(client, accepted["job_id"])
    assert body["status"] == "succeeded"
    assert body["kind"] == endpoint.removeprefix("/v1/")
    assert body["error"] is None
    assert body["result"] == {
        "exit_code": 1,
        "stdout": "partial output",
        "stderr": "Error: it broke",
    }


def test_plan_invokes_engine_with_targets_and_plan_file(tmp_path: Path) -> None:
    """The plan job passes the request's targets and plan_file through
    to the engine wrapper unchanged."""
    workspace = tmp_path / "ws"
    workspace.mkdir()

    ok = CommandResult(ok=True, stdout="Plan: 1 to add", stderr="", exit_code=0)
    with client_with() as client:
        with patch(
            "src.engine.plan", new_callable=AsyncMock, return_value=ok
        ) as plan_mock:
            response = client.post(
                "/v1/plan",
                json={
                    "workspace_path": str(workspace),
                    "targets": ["module.db"],
                    "plan_file": "abc123.plan",
                },
            )
            assert response.status_code == 202
            accepted: dict[str, str] = response.json()
            body = poll_until_terminal(client, accepted["job_id"])
    assert body["status"] == "succeeded"
    assert body["result"]["exit_code"] == 0
    plan_mock.assert_awaited_once_with("sh", workspace, ["module.db"], "abc123.plan")


def test_unexpected_error_fails_job_500(tmp_path: Path) -> None:
    """An unexpected exception in the operation is a service-level
    fault: the job ends `failed` with a 500 problem."""
    workspace = tmp_path / "ws"
    workspace.mkdir()

    with client_with() as client:
        with patch(
            "src.engine.init",
            new_callable=AsyncMock,
            side_effect=RuntimeError("subprocess exploded"),
        ):
            response = client.post(
                "/v1/init",
                json={"workspace_path": str(workspace)},
            )
            assert response.status_code == 202
            accepted: dict[str, str] = response.json()
            body = poll_until_terminal(client, accepted["job_id"])
    assert body["status"] == "failed"
    assert body["result"] is None
    assert body["error"]["status"] == 500
    assert "subprocess exploded" in body["error"]["detail"]


def test_get_job_404_when_unknown() -> None:
    with client_with() as client:
        response = client.get(f"/v1/jobs/{uuid.uuid4()}")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")


def test_get_job_422_when_malformed_id() -> None:
    with client_with() as client:
        response = client.get("/v1/jobs/not-a-uuid")
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")


def test_get_job_requires_token_when_configured() -> None:
    with client_with(token="expected") as client:
        response = client.get(f"/v1/jobs/{uuid.uuid4()}")
    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/problem+json")


def test_job_expires_after_ttl(tmp_path: Path) -> None:
    """With job_ttl=0, a terminal job is swept on the next poll → 404."""
    workspace = tmp_path / "ws"
    workspace.mkdir()

    init_failed = CommandResult(ok=False, stdout="", stderr="nope", exit_code=1)
    with client_with(job_ttl=0) as client:
        with patch("src.engine.init", new_callable=AsyncMock, return_value=init_failed):
            response = client.post(
                "/v1/init",
                json={"workspace_path": str(workspace)},
            )
            assert response.status_code == 202
            accepted: dict[str, str] = response.json()
            job_id = accepted["job_id"]
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


@pytest.mark.parametrize(
    ("endpoint", "extra"), [(endpoint, extra) for endpoint, _, extra in OPERATIONS]
)
def test_endpoints_accept_scope_id(endpoint: str, extra: dict[str, str]) -> None:
    """scope_id is accepted without 422 (extra='forbid' would reject
    unknown fields); the 404 comes from the nonexistent workspace."""
    with client_with() as client:
        response = client.post(
            endpoint,
            json={
                "workspace_path": "/tmp/does-not-exist",
                "scope_id": "sub-uuid-1234",
                **extra,
            },
        )
    assert response.status_code == 404


@pytest.mark.parametrize("endpoint", IMPORT_ENDPOINTS)
def test_import_endpoints_return_501(endpoint: str, tmp_path: Path) -> None:
    """Import is not implemented: a well-formed request against a real
    workspace still gets 501 and a problem document, and no job."""
    workspace = tmp_path / "ws"
    workspace.mkdir()

    with client_with() as client:
        response = client.post(
            endpoint,
            json={
                "workspace_path": str(workspace),
                "scope_id": "sub-1",
                "terraform_provider": "azure",
                "address": "azurerm_resource_group.main",
                "resource_id": "/subscriptions/x/resourceGroups/y",
            },
        )
    assert response.status_code == 501
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["status"] == 501
    assert "location" not in response.headers


@pytest.mark.parametrize("endpoint", IMPORT_ENDPOINTS)
def test_import_endpoints_501_regardless_of_request(endpoint: str) -> None:
    """The 501 precedes every submit-time check: no token, no body and
    a nonexistent workspace all still answer 501 rather than
    401/422/404."""
    with client_with(token="expected") as client:
        assert client.post(endpoint).status_code == 501
        assert client.post(endpoint, json={}).status_code == 501
        assert (
            client.post(
                endpoint, json={"workspace_path": "/tmp/does-not-exist"}
            ).status_code
            == 501
        )
