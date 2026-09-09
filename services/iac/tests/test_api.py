# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the IaC reference implementation.

These cover the contract surface: healthz, auth, request validation
(including the `plan_file` path-traversal guard), the
404-on-missing-workspace path, the 503 when the engine isn't installed,
the async job lifecycle (202 submit → poll to terminal), the raw
{exit_code, stdout, stderr} pass-through for every operation,
per-workspace FIFO queueing, and job expiry. They do NOT exercise an
actual terraform run against a cloud — that requires network and
credentials.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import ANY, AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from src import main as service_main
from src.cloud_cli import CloudCli
from src.cloud_cli._azure import AzureProvider
from src.cloud_cli._gcp import GcpProvider
from src.config import Config
from src.engine import CommandResult
from src.jobs import JobRegistry, WorkspaceQueue
from src.models import MissingCredentialError


# (endpoint, terraform function to stub, extra request fields)
OPERATIONS = [
    ("/v1/init", "src.engine.init", {}),
    ("/v1/validate", "src.engine.validate", {}),
    ("/v1/plan", "src.engine.plan", {"plan_file": "x.plan"}),
    ("/v1/show", "src.engine.show_plan_json", {"plan_file": "x.plan"}),
    ("/v1/apply", "src.engine.apply", {"plan_file": "x.plan"}),
    (
        "/v1/import",
        "src.engine.import_resource",
        {
            "address": "azurerm_resource_group.main",
            "resource_id": "/subscriptions/x/resourceGroups/y",
        },
    ),
]


# `scope_id` is required on every request and needs at least one provider
# with complete credentials, so the default test config carries a fake
# Azure service principal; the `az login` it would trigger is patched out.
_TEST_PROVIDER = {
    "azure_client_id": "test-client",
    "azure_client_secret": "test-secret",
    "azure_tenant_id": "test-tenant",
}


@contextmanager
def _client_with(
    token: str = "",
    iac_binary: str = "sh",
    job_ttl: int = 3600,
    **config_overrides,
):
    # `sh` stands in for the engine binary so the per-request binary
    # check passes in engine-less test environments; subprocess calls are
    # patched in every test that would reach them.
    service_main.config = Config(
        expected_token=token,
        iac_binary=iac_binary,
        job_ttl=job_ttl,
        **{**_TEST_PROVIDER, **config_overrides},
    )
    # Fresh queue/registry/orchestrator per test so job records and login
    # state don't leak across tests.
    service_main.workspace_queue = WorkspaceQueue()
    service_main.jobs = JobRegistry(
        ttl_seconds=job_ttl, workspace_queue=service_main.workspace_queue
    )
    service_main.cloud = CloudCli(service_main.config)
    with (
        patch.object(AzureProvider, "login", new_callable=AsyncMock),
        patch.object(GcpProvider, "login", new_callable=AsyncMock),
        TestClient(service_main.app) as client,
    ):
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


def test_init_requires_token_when_configured() -> None:
    with _client_with(token="expected") as client:
        response = client.post(
            "/v1/init",
            json={"workspace_path": "/tmp/anywhere", "scope_id": "sub-test"},
        )
    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/problem+json")


def test_init_503_when_engine_missing() -> None:
    with _client_with() as client:
        with patch("src.main.engine_available", return_value=False):
            response = client.post(
                "/v1/init",
                json={"workspace_path": "/tmp", "scope_id": "sub-test"},
            )
    assert response.status_code == 503
    assert response.headers["content-type"].startswith("application/problem+json")


def test_init_404_when_workspace_missing(tmp_path: Path) -> None:
    # The service should 404 before enqueueing anything because the
    # workspace path is bogus.
    with _client_with() as client:
        response = client.post(
            "/v1/init",
            json={
                "workspace_path": str(tmp_path / "does-not-exist"),
                "scope_id": "sub-test",
            },
        )
    assert response.status_code == 404


def test_init_request_validation_returns_problem_json() -> None:
    with _client_with() as client:
        response = client.post(
            "/v1/init",
            json={"workspace_path": "", "scope_id": "sub-test"},  # min_length=1
        )
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")


def test_plan_rejects_empty_target_string() -> None:
    with _client_with() as client:
        response = client.post(
            "/v1/plan",
            json={
                "workspace_path": "/tmp",
                "scope_id": "sub-test",
                "targets": [""],
                "plan_file": "x.plan",
            },
        )
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")


@pytest.mark.parametrize("endpoint", ["/v1/plan", "/v1/show", "/v1/apply"])
def test_plan_file_traversal_rejected(endpoint: str) -> None:
    """`plan_file` lands in `-out` / `show` / `apply` argv: anything
    that isn't a single path segment must be rejected at the schema."""
    with _client_with() as client:
        response = client.post(
            endpoint,
            json={
                "workspace_path": "/tmp",
                "scope_id": "sub-test",
                "plan_file": "../evil",
            },
        )
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")


def test_init_submit_returns_202_with_location(tmp_path: Path) -> None:
    """Submission returns 202 + JobAccepted and a Location header."""
    workspace = tmp_path / "ws"
    workspace.mkdir()

    init_failed = CommandResult(ok=False, stdout="", stderr="nope", exit_code=1)
    with _client_with() as client:
        with patch("src.engine.init", new_callable=AsyncMock, return_value=init_failed):
            response = client.post(
                "/v1/init",
                json={"workspace_path": str(workspace), "scope_id": "sub-test"},
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

    workspace = tmp_path / "ws"
    workspace.mkdir()

    release = threading.Event()

    async def blocked_init(*args, **kwargs):
        while not release.is_set():
            await asyncio.sleep(0.005)
        return CommandResult(ok=False, stdout="", stderr="init stubbed", exit_code=1)

    with _client_with() as client:
        with patch("src.engine.init", side_effect=blocked_init):
            first = client.post(
                "/v1/init",
                json={"workspace_path": str(workspace), "scope_id": "sub-test"},
            ).json()["job_id"]
            second = client.post(
                "/v1/init",
                json={"workspace_path": str(workspace), "scope_id": "sub-test"},
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
    assert first_body["result"]["exit_code"] == 1
    # FIFO: the second job started only after the first finished.
    assert datetime.fromisoformat(second_body["started_at"]) >= datetime.fromisoformat(
        first_body["finished_at"]
    )


@pytest.mark.parametrize(("endpoint", "tf_target", "extra"), OPERATIONS)
def test_op_job_returns_raw_result_verbatim(
    endpoint: str, tf_target: str, extra: dict, tmp_path: Path
) -> None:
    """A terraform-level failure is a `succeeded` job whose result is
    the raw {exit_code, stdout, stderr} — not a `failed` job, and not
    interpreted by the service."""
    workspace = tmp_path / "ws"
    workspace.mkdir()

    failed = CommandResult(
        ok=False, stdout="partial output", stderr="Error: it broke", exit_code=1
    )
    with _client_with() as client:
        with patch(tf_target, new_callable=AsyncMock, return_value=failed):
            response = client.post(
                endpoint,
                json={
                    "workspace_path": str(workspace),
                    "scope_id": "sub-test",
                    **extra,
                },
            )
            assert response.status_code == 202
            body = _poll_until_terminal(client, response.json()["job_id"])
    assert body["status"] == "succeeded"
    assert body["kind"] == endpoint.removeprefix("/v1/")
    assert body["error"] is None
    assert body["result"] == {
        "exit_code": 1,
        "stdout": "partial output",
        "stderr": "Error: it broke",
    }


def test_plan_invokes_terraform_with_targets_and_plan_file(tmp_path: Path) -> None:
    """The plan job passes the request's targets and plan_file through
    to the terraform wrapper unchanged."""
    workspace = tmp_path / "ws"
    workspace.mkdir()

    ok = CommandResult(ok=True, stdout="Plan: 1 to add", stderr="", exit_code=0)
    with _client_with() as client:
        with patch(
            "src.engine.plan", new_callable=AsyncMock, return_value=ok
        ) as plan_mock:
            response = client.post(
                "/v1/plan",
                json={
                    "workspace_path": str(workspace),
                    "scope_id": "sub-test",
                    "targets": ["module.db"],
                    "plan_file": "abc123.plan",
                },
            )
            assert response.status_code == 202
            body = _poll_until_terminal(client, response.json()["job_id"])
    assert body["status"] == "succeeded"
    assert body["result"]["exit_code"] == 0
    plan_mock.assert_awaited_once_with(
        "sh", workspace, ["module.db"], "abc123.plan", env=ANY
    )
    # The required scope_id is injected into the engine environment.
    assert plan_mock.await_args.kwargs["env"]["ARM_SUBSCRIPTION_ID"] == "sub-test"


def test_job_succeeded_log_reports_kind_and_exit_code(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """The engine no longer logs anything itself, so the job's terminal
    log line is the only place operators can see that a command ran and
    whether the engine exited non-zero."""
    workspace = tmp_path / "ws"
    workspace.mkdir()

    failed = CommandResult(ok=False, stdout="", stderr="Error: it broke", exit_code=1)
    caplog.set_level(logging.INFO, logger="src.jobs")
    # The lifespan's configure_logging() resets root handlers, which would
    # detach caplog; the log format is not under test here.
    with patch("src.main.configure_logging"), _client_with() as client:
        with patch("src.engine.plan", new_callable=AsyncMock, return_value=failed):
            response = client.post(
                "/v1/plan",
                json={
                    "workspace_path": str(workspace),
                    "scope_id": "sub-test",
                    "plan_file": "abc123.plan",
                },
            )
            assert response.status_code == 202
            body = _poll_until_terminal(client, response.json()["job_id"])
    assert body["status"] == "succeeded"

    succeeded = [
        r for r in caplog.records if r.getMessage().startswith("job succeeded")
    ]
    assert len(succeeded) == 1
    message = succeeded[0].getMessage()
    assert f"job_id={body['job_id']}" in message
    assert "kind=plan" in message
    assert "exit_code=1" in message
    assert "elapsed=" in message


def test_init_passes_backend_config_when_set(tmp_path: Path) -> None:
    """When TF_BACKEND_CONFIG is set, init passes -backend-config to terraform."""
    workspace = tmp_path / "ws"
    workspace.mkdir()

    ok = CommandResult(ok=True, stdout="Initialized", stderr="", exit_code=0)
    with _client_with(backend_config="backend.tfbackend") as client:
        with patch(
            "src.engine.init", new_callable=AsyncMock, return_value=ok
        ) as init_mock:
            response = client.post(
                "/v1/init",
                json={"workspace_path": str(workspace), "scope_id": "sub-test"},
            )
            assert response.status_code == 202
            _poll_until_terminal(client, response.json()["job_id"])
    init_mock.assert_awaited_once_with(
        "sh", workspace, backend_config="backend.tfbackend", env=ANY
    )


def test_init_omits_backend_config_when_empty(tmp_path: Path) -> None:
    """When TF_BACKEND_CONFIG is not set, init is called without backend_config."""
    workspace = tmp_path / "ws"
    workspace.mkdir()

    ok = CommandResult(ok=True, stdout="Initialized", stderr="", exit_code=0)
    with _client_with() as client:
        with patch(
            "src.engine.init", new_callable=AsyncMock, return_value=ok
        ) as init_mock:
            response = client.post(
                "/v1/init",
                json={"workspace_path": str(workspace), "scope_id": "sub-test"},
            )
            assert response.status_code == 202
            _poll_until_terminal(client, response.json()["job_id"])
    init_mock.assert_awaited_once_with("sh", workspace, backend_config="", env=ANY)


def test_unexpected_error_fails_job_500(tmp_path: Path) -> None:
    """An unexpected exception in the operation is a service-level
    fault: the job ends `failed` with a 500 problem."""
    workspace = tmp_path / "ws"
    workspace.mkdir()

    with _client_with() as client:
        with patch(
            "src.engine.init",
            new_callable=AsyncMock,
            side_effect=RuntimeError("subprocess exploded"),
        ):
            response = client.post(
                "/v1/init",
                json={"workspace_path": str(workspace), "scope_id": "sub-test"},
            )
            assert response.status_code == 202
            body = _poll_until_terminal(client, response.json()["job_id"])
    assert body["status"] == "failed"
    assert body["result"] is None
    assert body["error"]["status"] == 500
    assert "subprocess exploded" in body["error"]["detail"]


def test_unhandled_exception_returns_generic_problem_detail() -> None:
    """A crash inside a request handler is logged with its traceback; the
    client only gets the request id to correlate with, never the
    exception text (which may carry paths or CLI output)."""
    with _client_with() as client:
        client_no_raise = TestClient(service_main.app, raise_server_exceptions=False)
        with patch.object(
            service_main,
            "engine_available",
            side_effect=RuntimeError("secret-bearing message"),
        ):
            response = client_no_raise.post(
                "/v1/init",
                json={"workspace_path": "/tmp", "scope_id": "sub-test"},
                headers={"x-request-id": "req-123"},
            )
    assert response.status_code == 500
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert "secret-bearing message" not in body["detail"]
    assert "req-123" in body["detail"]
    del client


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
    workspace = tmp_path / "ws"
    workspace.mkdir()

    init_failed = CommandResult(ok=False, stdout="", stderr="nope", exit_code=1)
    with _client_with(job_ttl=0) as client:
        with patch("src.engine.init", new_callable=AsyncMock, return_value=init_failed):
            response = client.post(
                "/v1/init",
                json={"workspace_path": str(workspace), "scope_id": "sub-test"},
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


@pytest.mark.parametrize(("endpoint", "tf_target", "extra"), OPERATIONS)
def test_endpoints_accept_scope_id(endpoint: str, tf_target: str, extra: dict) -> None:
    """scope_id passes schema validation; the 404 comes from the
    nonexistent workspace, proving validation ran first."""
    with _client_with() as client:
        response = client.post(
            endpoint,
            json={
                "workspace_path": "/tmp/does-not-exist",
                "scope_id": "sub-uuid-1234",
                **extra,
            },
        )
    assert response.status_code == 404


@pytest.mark.parametrize(("endpoint", "tf_target", "extra"), OPERATIONS)
@pytest.mark.parametrize("scope", [None, ""], ids=["missing", "empty"])
def test_endpoints_require_scope_id(
    endpoint: str, tf_target: str, extra: dict, scope: str | None
) -> None:
    """The contract makes scope_id required (minLength 1) on every
    engine command: omitting it or sending "" is a schema 422."""
    body = {"workspace_path": "/tmp", **extra}
    if scope is not None:
        body["scope_id"] = scope
    with _client_with() as client:
        response = client.post(endpoint, json=body)
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")


def test_job_fails_422_when_no_provider_is_configured(tmp_path: Path) -> None:
    """A scope needs a provider to apply to: with no complete credentials
    the job ends failed(422) listing what is missing, before the engine
    is ever invoked."""
    workspace = tmp_path / "ws"
    workspace.mkdir()

    with _client_with(
        azure_client_id="", azure_client_secret="", azure_tenant_id=""
    ) as client:
        with patch("src.engine.init", new_callable=AsyncMock) as init:
            response = client.post(
                "/v1/init",
                json={"workspace_path": str(workspace), "scope_id": "sub-1"},
            )
            assert response.status_code == 202
            body = _poll_until_terminal(client, response.json()["job_id"])
    assert body["status"] == "failed"
    assert body["error"]["status"] == 422
    assert "No cloud provider credentials are complete" in body["error"]["detail"]
    init.assert_not_awaited()


def test_startup_aborts_when_aws_keys_are_incomplete() -> None:
    """An access key ID without its secret is not usable by the AWS CLI or
    the provider. It is a deployment error, so it must fail the boot naming
    the missing variable instead of being silently skipped and letting the
    engine fail later with an opaque auth error."""
    service_main.config = Config(
        expected_token="", iac_binary="sh", aws_access_key_id="AKIA-test"
    )
    service_main.cloud = CloudCli(service_main.config)
    with pytest.raises(MissingCredentialError) as exc_info:
        with TestClient(service_main.app):
            pass
    assert exc_info.value.missing == {"AWS": ["AWS_SECRET_ACCESS_KEY"]}


_STATE_DOC = {
    "version": 4,
    "resources": [
        {
            "mode": "managed",
            "type": "azurerm_resource_group",
            "instances": [
                {"attributes": {"id": "/subscriptions/s/resourceGroups/rg1"}},
                {"attributes": {"id": "/subscriptions/s/resourceGroups/rg2"}},
            ],
        },
        {
            "mode": "data",
            "type": "azurerm_client_config",
            "instances": [{"attributes": {"id": "data-id-ignored"}}],
        },
        {
            "mode": "managed",
            "type": "azurerm_storage_account",
            "instances": [{"attributes": {}}],
        },
    ],
}


def test_state_resource_ids_returns_managed_ids(tmp_path: Path) -> None:
    """stdout is a JSON array of the managed instances' provider ids;
    data resources and id-less instances are skipped."""
    workspace = tmp_path / "ws"
    workspace.mkdir()

    pulled = CommandResult(
        ok=True, stdout=json.dumps(_STATE_DOC), stderr="", exit_code=0
    )
    with _client_with() as client:
        with patch(
            "src.engine.state_pull", new_callable=AsyncMock, return_value=pulled
        ):
            response = client.post(
                "/v1/import/state-resource-ids",
                json={"workspace_path": str(workspace), "scope_id": "sub-test"},
            )
            assert response.status_code == 202
            body = _poll_until_terminal(client, response.json()["job_id"])
    assert body["status"] == "succeeded"
    assert body["kind"] == "state_resource_ids"
    assert body["result"]["exit_code"] == 0
    assert json.loads(body["result"]["stdout"]) == [
        "/subscriptions/s/resourceGroups/rg1",
        "/subscriptions/s/resourceGroups/rg2",
    ]


def test_state_resource_ids_passes_pull_failure_through(tmp_path: Path) -> None:
    """A failed `state pull` is a succeeded job carrying the command's
    exit code and stderr; stdout is empty rather than partial state."""
    workspace = tmp_path / "ws"
    workspace.mkdir()

    pulled = CommandResult(
        ok=False, stdout="partial", stderr="Error: no state", exit_code=1
    )
    with _client_with() as client:
        with patch(
            "src.engine.state_pull", new_callable=AsyncMock, return_value=pulled
        ):
            response = client.post(
                "/v1/import/state-resource-ids",
                json={"workspace_path": str(workspace), "scope_id": "sub-test"},
            )
            assert response.status_code == 202
            body = _poll_until_terminal(client, response.json()["job_id"])
    assert body["status"] == "succeeded"
    assert body["result"] == {
        "exit_code": 1,
        "stdout": "",
        "stderr": "Error: no state",
    }


def test_scope_resource_ids_returns_cli_result_verbatim(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()

    listed = CommandResult(ok=True, stdout='["id-1", "id-2"]', stderr="", exit_code=0)
    with _client_with() as client:
        with (
            patch.object(service_main.cloud, "cli_available", return_value=True),
            patch.object(
                service_main.cloud,
                "scope_resource_ids",
                new_callable=AsyncMock,
                return_value=listed,
            ) as list_mock,
        ):
            response = client.post(
                "/v1/import/scope-resource-ids",
                json={
                    "workspace_path": str(workspace),
                    "scope_id": "sub-1",
                    "terraform_provider": "azure",
                },
            )
            assert response.status_code == 202
            body = _poll_until_terminal(client, response.json()["job_id"])
    assert body["status"] == "succeeded"
    assert body["kind"] == "scope_resource_ids"
    assert body["result"] == {
        "exit_code": 0,
        "stdout": '["id-1", "id-2"]',
        "stderr": "",
    }
    list_mock.assert_awaited_once_with("azure", "sub-1")


def test_scope_resource_ids_validation() -> None:
    """scope_id and terraform_provider are required, and the provider
    must be one of azure/gcp/aws."""
    payloads = [
        {"workspace_path": "/tmp"},
        {"workspace_path": "/tmp", "scope_id": "sub-1"},
        {"workspace_path": "/tmp", "terraform_provider": "azure"},
        {"workspace_path": "/tmp", "scope_id": "sub-1", "terraform_provider": "oci"},
        {"workspace_path": "/tmp", "scope_id": "", "terraform_provider": "azure"},
    ]
    with _client_with() as client:
        for payload in payloads:
            response = client.post("/v1/import/scope-resource-ids", json=payload)
            assert response.status_code == 422, payload


def test_scope_resource_ids_503_when_cli_missing(tmp_path: Path) -> None:
    """Like the terraform binary, a missing cloud CLI is a submit-time
    503, not a job-level failure."""
    workspace = tmp_path / "ws"
    workspace.mkdir()

    with _client_with() as client:
        with patch.object(service_main.cloud, "cli_available", return_value=False):
            response = client.post(
                "/v1/import/scope-resource-ids",
                json={
                    "workspace_path": str(workspace),
                    "scope_id": "sub-1",
                    "terraform_provider": "gcp",
                },
            )
    assert response.status_code == 503
    assert response.headers["content-type"].startswith("application/problem+json")
    # The message names the CLI binary of the requested provider.
    assert "gcloud" in response.json()["detail"]
