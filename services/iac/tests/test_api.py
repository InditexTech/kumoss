# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the IaC reference implementation.

These cover the contract surface: healthz, auth, request validation
(including the `plan_file` path-traversal guard, the `env` every
command takes and the names it may not set, the `vars` only `plan` and
`import` take, and the `provider` / `scope_id` pair of scope
discovery), env and vars reaching the engine untouched, the
404-on-missing-workspace path,
the async job lifecycle (202 submit → poll to terminal), the raw
{exit_code, stdout, stderr} pass-through for every operation, the
import endpoints' ID listing and their discovery failure planes,
per-workspace FIFO queueing,
job expiry, and the backend flags `init` runs with. They do NOT
exercise an actual engine run against a cloud — that requires network
and credentials.
"""

from __future__ import annotations

import json
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
from src.discovery import ScopeDiscovery
from src.exceptions import DiscoveryError
from src.state import StateResourceIds


ENV_VALUES: dict[str, str] = {"ARM_SUBSCRIPTION_ID": "sub-uuid-1234"}
ENV: dict[str, Any] = {"env": ENV_VALUES}
DISCOVERY_SCOPE: dict[str, Any] = {"scope_id": "sub-uuid-1234", "provider": "azurerm"}

# (endpoint, engine method to stub, the body fields besides
# workspace_path that the endpoint documents)
OPERATIONS: list[tuple[str, str, dict[str, Any]]] = [
    ("/v1/init", "src.engine.IacEngine.init", {**ENV}),
    ("/v1/validate", "src.engine.IacEngine.validate", {**ENV}),
    ("/v1/plan", "src.engine.IacEngine.plan", {"plan_file": "x.plan", **ENV}),
    (
        "/v1/show",
        "src.engine.IacEngine.show_plan_json",
        {"plan_file": "x.plan", **ENV},
    ),
    ("/v1/apply", "src.engine.IacEngine.apply", {"plan_file": "x.plan", **ENV}),
    (
        "/v1/import",
        "src.engine.IacEngine.import_resource",
        {
            "address": "azurerm_resource_group.main",
            "resource_id": "/subscriptions/x/resourceGroups/y",
            **ENV,
        },
    ),
]

EXTRA: dict[str, dict[str, Any]] = {
    endpoint: extra for endpoint, _, extra in OPERATIONS
} | {
    "/v1/import/state-resource-ids": {},
    "/v1/import/scope-resource-ids": {**DISCOVERY_SCOPE},
}

# The endpoints that run an engine command, and so take `env`.
COMMAND_ENDPOINTS: list[str] = [endpoint for endpoint, _, _ in OPERATIONS]

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
    backend_config: str | None = None,
) -> Generator[TestClient]:
    # `sh` stands in for the engine so Config's fail-fast binary check
    # passes in engine-less test environments; subprocess calls are
    # patched in every test that would reach them.
    service_main.config = Config(
        expected_token=token,
        iac_binary=iac_binary,
        backend_config=backend_config,
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


@pytest.mark.parametrize(
    "headers",
    [
        pytest.param({}, id="no-authorization-header"),
        pytest.param({"Authorization": "Basic Zm9vOmJhcg=="}, id="wrong-scheme"),
        pytest.param({"Authorization": "Bearer nope"}, id="wrong-token"),
    ],
)
def test_init_requires_token_when_configured(headers: dict[str, str]) -> None:
    with client_with(token="expected") as client:
        response = client.post(
            "/v1/init",
            json={"workspace_path": "/tmp/anywhere", **ENV},
            headers=headers,
        )
    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_init_404_when_workspace_missing(tmp_path: Path) -> None:
    # The service should 404 before enqueueing anything because the
    # workspace path is bogus.
    with client_with() as client:
        response = client.post(
            "/v1/init",
            json={"workspace_path": str(tmp_path / "does-not-exist"), **ENV},
        )
    assert response.status_code == 404


def test_init_request_validation_returns_problem_json() -> None:
    with client_with() as client:
        response = client.post(
            "/v1/init",
            json={"workspace_path": "", **ENV},
        )
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")


def test_plan_rejects_empty_target_string() -> None:
    with client_with() as client:
        response = client.post(
            "/v1/plan",
            json={
                "workspace_path": "/tmp",
                "targets": [""],
                "plan_file": "x.plan",
                **ENV,
            },
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
            json={"workspace_path": "/tmp", **EXTRA[endpoint], "plan_file": "../evil"},
        )
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")


def test_init_submit_returns_202_with_location(tmp_path: Path) -> None:
    """Submission returns 202 + JobAccepted and a Location header."""
    workspace = tmp_path / "ws"
    workspace.mkdir()

    init_failed = CommandResult(ok=False, stdout="", stderr="nope", exit_code=1)
    with client_with() as client:
        with patch(
            "src.engine.IacEngine.init",
            new_callable=AsyncMock,
            return_value=init_failed,
        ):
            response = client.post(
                "/v1/init",
                json={"workspace_path": str(workspace), **ENV},
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
        with patch("src.engine.IacEngine.init", side_effect=blocked_init):
            first: str = client.post(
                "/v1/init", json={"workspace_path": str(workspace), **ENV}
            ).json()["job_id"]
            second: str = client.post(
                "/v1/init", json={"workspace_path": str(workspace), **ENV}
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


def test_plan_invokes_engine_with_targets_plan_file_and_env(tmp_path: Path) -> None:
    """The plan job passes the request's targets, plan_file and env
    through to the engine wrapper unchanged."""
    workspace = tmp_path / "ws"
    workspace.mkdir()

    ok = CommandResult(ok=True, stdout="Plan: 1 to add", stderr="", exit_code=0)
    with client_with() as client:
        with patch(
            "src.engine.IacEngine.plan", new_callable=AsyncMock, return_value=ok
        ) as plan_mock:
            body = submit_and_poll(
                client,
                "/v1/plan",
                {
                    "workspace_path": str(workspace),
                    "targets": ["module.db"],
                    "plan_file": "abc123.plan",
                    **ENV,
                },
            )
    assert body["status"] == "succeeded"
    assert body["result"]["exit_code"] == 0
    plan_mock.assert_awaited_once_with(
        workspace, ["module.db"], "abc123.plan", ENV_VALUES, [], {}
    )


@pytest.mark.parametrize("endpoint", ["/v1/plan", "/v1/import"])
def test_vars_reach_the_engine_untouched(endpoint: str, tmp_path: Path) -> None:
    """`vars` is passed as is; nothing in the service interprets it."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    target = dict((e, t) for e, t, _ in OPERATIONS)[endpoint]
    variables = {"region": {"location": "westeurope"}, "pw": "s3cr3t", "n": 3}

    ok = CommandResult(ok=True, stdout="", stderr="", exit_code=0)
    with client_with() as client:
        with patch(target, new_callable=AsyncMock, return_value=ok) as mock:
            body = submit_and_poll(
                client,
                endpoint,
                {
                    "workspace_path": str(workspace),
                    **EXTRA[endpoint],
                    "vars": variables,
                },
            )
    assert body["status"] == "succeeded"
    assert mock.await_args is not None
    assert mock.await_args.args[-1] == variables


def test_rejected_vars_are_not_echoed() -> None:
    """A 422 names the offending field, never the submitted values."""
    with client_with() as client:
        response = client.post(
            "/v1/plan",
            json={
                "workspace_path": "/tmp",
                "plan_file": "x.plan",
                "vars": {"not a name": "s3cr3t-value"},
            },
        )
    assert response.status_code == 422
    assert "s3cr3t-value" not in response.text
    assert "vars" in response.text


@pytest.mark.parametrize(
    "endpoint", ["/v1/init", "/v1/validate", "/v1/show", "/v1/apply"]
)
@pytest.mark.parametrize(
    "field",
    [
        pytest.param({"vars": {"a": 1}}, id="vars"),
        pytest.param({"var_files": ["a.tfvars"]}, id="var_files"),
    ],
)
def test_only_plan_and_import_take_inputs(endpoint: str, field: dict[str, Any]) -> None:
    with client_with() as client:
        response = client.post(
            endpoint,
            json={"workspace_path": "/tmp", **EXTRA[endpoint], **field},
        )
    assert response.status_code == 422


@pytest.mark.parametrize("endpoint", ["/v1/plan", "/v1/import"])
def test_var_files_reach_the_engine_in_order(endpoint: str, tmp_path: Path) -> None:
    """Any path shape inside the workspace is passed on as given."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    target = dict((e, t) for e, t, _ in OPERATIONS)[endpoint]
    var_files = ["envs/b.tfvars", "envs/my env.tfvars", "a.tfvars.json"]

    ok = CommandResult(ok=True, stdout="", stderr="", exit_code=0)
    with client_with() as client:
        with patch(target, new_callable=AsyncMock, return_value=ok) as mock:
            body = submit_and_poll(
                client,
                endpoint,
                {
                    "workspace_path": str(workspace),
                    **EXTRA[endpoint],
                    "var_files": var_files,
                    "vars": {"x": 1},
                },
            )
    assert body["status"] == "succeeded"
    assert mock.await_args is not None
    assert mock.await_args.args[-2:] == (var_files, {"x": 1})


@pytest.mark.parametrize("endpoint", ["/v1/plan", "/v1/import"])
@pytest.mark.parametrize(
    "path",
    [
        pytest.param("/etc/x.tfvars", id="absolute"),
        pytest.param("../x.tfvars", id="parent"),
        pytest.param("envs/../../x.tfvars", id="nested-parent"),
        pytest.param("a\x00b.tfvars", id="nul"),
        pytest.param("", id="empty"),
    ],
)
def test_var_files_outside_the_workspace_are_422(
    endpoint: str, path: str, tmp_path: Path
) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    with client_with() as client:
        response = client.post(
            endpoint,
            json={
                "workspace_path": str(workspace),
                **EXTRA[endpoint],
                "var_files": [path],
            },
        )
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    assert "location" not in response.headers


@pytest.mark.parametrize("endpoint", ["/v1/plan", "/v1/import"])
def test_a_var_file_symlinked_out_of_the_workspace_fails_the_command(
    endpoint: str, tmp_path: Path
) -> None:
    """Caught when the job runs: exit code 1, and the engine never starts."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    outside = tmp_path / "secret.tfvars"
    _ = outside.write_text('a = "b"\n')
    (workspace / "link.tfvars").symlink_to(outside)

    with client_with() as client:
        with patch("src.engine.IacEngine._run", new_callable=AsyncMock) as run:
            body = submit_and_poll(
                client,
                endpoint,
                {
                    "workspace_path": str(workspace),
                    **EXTRA[endpoint],
                    "var_files": ["link.tfvars"],
                },
            )
    run.assert_not_awaited()
    assert body["status"] == "succeeded"
    assert body["result"] == {
        "exit_code": 1,
        "stdout": "",
        "stderr": "var file link.tfvars resolves outside the workspace",
    }


def test_init_invokes_engine_with_the_request_env(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()

    ok = CommandResult(ok=True, stdout="has been initialized", stderr="")
    with client_with() as client:
        with patch(
            "src.engine.IacEngine.init", new_callable=AsyncMock, return_value=ok
        ) as init_mock:
            body = submit_and_poll(
                client, "/v1/init", {"workspace_path": str(workspace), **ENV}
            )
    assert body["status"] == "succeeded"
    assert body["result"]["exit_code"] == 0
    init_mock.assert_awaited_once_with(workspace, ENV_VALUES)


def _init_argv(client: TestClient, workspace: Path) -> list[str]:
    """Submit an init job with the engine subprocess stubbed, and return
    the argv the engine wrapper assembled."""
    ok = CommandResult(ok=True, stdout="has been initialized", stderr="")
    with patch(
        "src.engine.IacEngine._run", new_callable=AsyncMock, return_value=ok
    ) as run:
        response = client.post(
            "/v1/init", json={"workspace_path": str(workspace), **ENV}
        )
        assert response.status_code == 202, response.text
        accepted: dict[str, str] = response.json()
        job = poll_until_terminal(client, accepted["job_id"])
    assert job["status"] == "succeeded", job
    assert run.await_args is not None
    args: list[str] = run.await_args.args[0]
    return args


def test_init_always_reconfigures(tmp_path: Path) -> None:
    """`-input=false` cannot answer the "Backend configuration changed"
    prompt, so a workspace bound to another backend must be rebound
    rather than asked about."""
    workspace = tmp_path / "ws"
    workspace.mkdir()

    with client_with() as client:
        args = _init_argv(client, workspace)

    assert args == ["init", "-no-color", "-input=false", "-reconfigure"]


def test_init_passes_the_backend_config_file(tmp_path: Path) -> None:
    """A deployment that supplies its own backend configuration file
    gets it on the command line instead."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    path = tmp_path / "backend.hcl"
    _ = path.write_text('bucket = "somewhere"\n', encoding="utf-8")

    with client_with(backend_config=str(path)) as client:
        args = _init_argv(client, workspace)

    assert args[-1] == f"-backend-config={path}"
    assert "-reconfigure" in args


def _always_available(_self: Config, _binary: str) -> bool:
    return True


def test_job_execs_the_configured_engine_binary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The engine each job runs on is built from the current config:
    `IAC_BINARY` is the executable that gets spawned, in the workspace
    the request named."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setattr(Config, "_engine_available", _always_available)

    proc = AsyncMock()
    proc.communicate.return_value = (b"has been initialized", b"")
    proc.returncode = 0

    with client_with(iac_binary="terraform") as client:
        with patch(
            "asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=proc
        ) as spawn:
            response = client.post(
                "/v1/init", json={"workspace_path": str(workspace), **ENV}
            )
            assert response.status_code == 202, response.text
            accepted: dict[str, str] = response.json()
            job = poll_until_terminal(client, accepted["job_id"])

    assert job["status"] == "succeeded", job
    assert spawn.await_args is not None
    assert spawn.await_args.args[0] == "terraform"
    assert spawn.await_args.kwargs["cwd"] == str(workspace)


def test_unexpected_error_fails_job_500(tmp_path: Path) -> None:
    """An unexpected exception in the operation is a service-level
    fault: the job ends `failed` with a 500 problem."""
    workspace = tmp_path / "ws"
    workspace.mkdir()

    with client_with() as client:
        with patch(
            "src.engine.IacEngine.init",
            new_callable=AsyncMock,
            side_effect=RuntimeError("subprocess exploded"),
        ):
            response = client.post(
                "/v1/init",
                json={"workspace_path": str(workspace), **ENV},
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
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_job_expires_after_ttl(tmp_path: Path) -> None:
    """With job_ttl=0, a terminal job is swept on the next poll → 404."""
    workspace = tmp_path / "ws"
    workspace.mkdir()

    init_failed = CommandResult(ok=False, stdout="", stderr="nope", exit_code=1)
    with client_with(job_ttl=0) as client:
        with patch(
            "src.engine.IacEngine.init",
            new_callable=AsyncMock,
            return_value=init_failed,
        ):
            response = client.post(
                "/v1/init",
                json={"workspace_path": str(workspace), **ENV},
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
def test_endpoints_accept_their_documented_body(
    endpoint: str, extra: dict[str, Any]
) -> None:
    """The body each endpoint documents validates: the only thing wrong
    here is the nonexistent workspace, so the answer is 404 not 422."""
    with client_with() as client:
        response = client.post(
            endpoint,
            json={"workspace_path": "/tmp/does-not-exist", **extra},
        )
    assert response.status_code == 404


@pytest.mark.parametrize("endpoint", COMMAND_ENDPOINTS)
@pytest.mark.parametrize(
    "env",
    [
        pytest.param(None, id="omitted"),
        pytest.param({}, id="empty"),
        pytest.param({"GOOGLE_PROJECT": "p", "TF_VAR_x": "1"}, id="several"),
    ],
)
def test_command_endpoints_take_env_optionally(
    endpoint: str, env: dict[str, str] | None
) -> None:
    """`env` is optional and may be empty: the only thing wrong here is
    the nonexistent workspace, so 404 not 422."""
    body: dict[str, object] = {
        "workspace_path": "/tmp/does-not-exist",
        **EXTRA[endpoint],
    }
    _ = body.pop("env", None)
    if env is not None:
        body["env"] = env

    with client_with() as client:
        response = client.post(endpoint, json=body)
    assert response.status_code == 404


@pytest.mark.parametrize("endpoint", COMMAND_ENDPOINTS)
@pytest.mark.parametrize(
    "name",
    [
        "IAC_TEST_ALREADY_SET",
        "TF_CLI_ARGS",
        "TF_CLI_ARGS_plan",
        "TF_DATA_DIR",
        "TF_CLI_CONFIG_FILE",
        "TF_LOG_PATH",
        "TF_WORKSPACE",
        "TOFU_ENABLE_STATIC_SOURCE_EVALUATION",
        "TERRAFORM_CONFIG",
        "LD_PRELOAD",
        "DYLD_INSERT_LIBRARIES",
        "BASH_ENV",
        "GODEBUG",
        "SSL_CERT_FILE",
        "HTTPS_PROXY",
        "https_proxy",
        "NO_PROXY",
    ],
)
def test_env_cannot_replace_or_reserve(
    endpoint: str, name: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A request adds to the service's environment and never overrides
    it: a name the service already sets, or one that would change the
    command line, is a 422 Problem at submission and no job."""
    monkeypatch.setenv("IAC_TEST_ALREADY_SET", "ambient")
    workspace = tmp_path / "ws"
    workspace.mkdir()
    body = {
        "workspace_path": str(workspace),
        **EXTRA[endpoint],
        "env": {"GOOGLE_PROJECT": "p", name: "x"},
    }

    with client_with() as client:
        response = client.post(endpoint, json=body)
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    # HTTPExceptions carry their message in the Problem's title.
    problem = response.json()
    assert name in problem["title"]
    assert "GOOGLE_PROJECT" not in problem["title"]
    assert "location" not in response.headers


@pytest.mark.parametrize("endpoint", COMMAND_ENDPOINTS)
@pytest.mark.parametrize(
    "env",
    [
        pytest.param({"": "x"}, id="empty-name"),
        pytest.param({"1X": "x"}, id="leading-digit"),
        pytest.param({"A-B": "x"}, id="dash"),
        pytest.param({"A": 1}, id="non-string-value"),
        pytest.param({"A": "a\x00b"}, id="nul-in-value"),
        pytest.param(["A=x"], id="not-an-object"),
    ],
)
def test_command_endpoints_reject_malformed_env(endpoint: str, env: object) -> None:
    with client_with() as client:
        response = client.post(
            endpoint, json={"workspace_path": "/tmp", **EXTRA[endpoint], "env": env}
        )
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    # Rejected at submission: no job was created.
    assert "location" not in response.headers


@pytest.mark.parametrize("endpoint", COMMAND_ENDPOINTS)
@pytest.mark.parametrize(
    "field",
    [
        pytest.param({"scopes": []}, id="scopes"),
        pytest.param({"scope_id": "s"}, id="scope_id"),
        pytest.param({"terraform_provider": "azure"}, id="terraform_provider"),
        pytest.param({"variables": {"a": 1}}, id="variables"),
    ],
)
def test_pre_2_0_fields_are_rejected(endpoint: str, field: dict[str, Any]) -> None:
    with client_with() as client:
        response = client.post(
            endpoint, json={"workspace_path": "/tmp", **EXTRA[endpoint], **field}
        )
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")


@pytest.mark.parametrize(
    "field",
    [
        pytest.param({"env": {"X": "1"}}, id="env"),
        pytest.param({"scope_id": "s"}, id="scope_id"),
        pytest.param({"provider": "azurerm"}, id="provider"),
    ],
)
def test_state_resource_ids_takes_only_the_workspace(field: dict[str, Any]) -> None:
    with client_with() as client:
        response = client.post(
            "/v1/import/state-resource-ids",
            json={"workspace_path": "/tmp", **field},
        )
    assert response.status_code == 422


@pytest.mark.parametrize("missing", ["scope_id", "provider"])
def test_scope_resource_ids_requires_the_scope(missing: str) -> None:
    body: dict[str, object] = {"workspace_path": "/tmp", **DISCOVERY_SCOPE}
    del body[missing]

    with client_with() as client:
        response = client.post("/v1/import/scope-resource-ids", json=body)
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")


@pytest.mark.parametrize(
    "bad",
    [
        pytest.param({"scope_id": ""}, id="scope_id-empty"),
        pytest.param({"provider": "azure"}, id="provider-core-name"),
        pytest.param({"provider": "gcp"}, id="provider-core-name-gcp"),
        pytest.param({"provider": "oci"}, id="provider-without-discovery"),
        pytest.param({"provider": "kubernetes"}, id="provider-kubernetes"),
        pytest.param({"provider": "alibaba"}, id="provider-unknown"),
        pytest.param(
            {"scopes": [{"provider": "azurerm", "scope_id": "s"}]}, id="scopes"
        ),
        pytest.param({"env": {"X": "1"}}, id="env"),
        pytest.param({"terraform_provider": "azure"}, id="terraform_provider"),
    ],
)
def test_scope_resource_ids_rejects_a_malformed_scope(bad: dict[str, object]) -> None:
    """Discovery takes one provider it can list, by Terraform name."""
    body: dict[str, object] = {"workspace_path": "/tmp", **DISCOVERY_SCOPE, **bad}

    with client_with() as client:
        response = client.post("/v1/import/scope-resource-ids", json=body)
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")


def test_state_resource_ids_runs_on_the_service_environment(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()

    ok = CommandResult(ok=True, stdout="{}", stderr="", exit_code=0)
    with client_with() as client:
        with patch(
            "src.engine.IacEngine.state_pull", new_callable=AsyncMock, return_value=ok
        ) as mock:
            _ = submit_and_poll(
                client,
                "/v1/import/state-resource-ids",
                {"workspace_path": str(workspace)},
            )
    mock.assert_awaited_once_with(workspace)


@pytest.mark.parametrize(
    ("endpoint", "engine_target", "tail"),
    [
        ("/v1/validate", "src.engine.IacEngine.validate", ()),
        ("/v1/show", "src.engine.IacEngine.show_plan_json", ("x.plan",)),
        ("/v1/apply", "src.engine.IacEngine.apply", ("x.plan",)),
    ],
)
def test_commands_pass_the_request_env(
    endpoint: str, engine_target: str, tail: tuple[object, ...], tmp_path: Path
) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()

    ok = CommandResult(ok=True, stdout="", stderr="", exit_code=0)
    with client_with() as client:
        with patch(engine_target, new_callable=AsyncMock, return_value=ok) as mock:
            _ = submit_and_poll(
                client, endpoint, {"workspace_path": str(workspace), **EXTRA[endpoint]}
            )
    mock.assert_awaited_once_with(workspace, *tail, ENV_VALUES)


STATE_DOCUMENT: str = json.dumps(
    {
        "version": 4,
        "resources": [
            {
                "mode": "managed",
                "type": "azurerm_resource_group",
                "name": "main",
                "instances": [
                    {"attributes": {"id": "/subscriptions/s/resourceGroups/rg"}}
                ],
            },
            {
                "mode": "data",
                "type": "azurerm_client_config",
                "name": "current",
                "instances": [{"attributes": {"id": "not-a-managed-resource"}}],
            },
        ],
    }
)


class FakeLister:
    """A scope lister with a canned answer, recording what it was asked."""

    def __init__(
        self, ids: list[str] | None = None, error: Exception | None = None
    ) -> None:
        self._ids: list[str] = [] if ids is None else ids
        self._error: Exception | None = error
        self.scopes: list[str] = []

    async def list_resource_ids(self, scope_id: str) -> list[str]:
        self.scopes.append(scope_id)
        if self._error is not None:
            raise self._error
        return self._ids


def submit_and_poll(
    client: TestClient, endpoint: str, body: dict[str, object]
) -> dict[str, Any]:
    response = client.post(endpoint, json=body)
    assert response.status_code == 202, response.text
    accepted: dict[str, str] = response.json()
    return poll_until_terminal(client, accepted["job_id"])


def run_state_resource_ids(pulled: CommandResult, workspace: Path) -> dict[str, Any]:
    with client_with() as client:
        with patch(
            "src.engine.IacEngine.state_pull",
            new_callable=AsyncMock,
            return_value=pulled,
        ):
            return submit_and_poll(
                client,
                "/v1/import/state-resource-ids",
                {"workspace_path": str(workspace)},
            )


def post_scope_resource_ids(
    client: TestClient, workspace: Path, provider: str
) -> dict[str, Any]:
    return submit_and_poll(
        client,
        "/v1/import/scope-resource-ids",
        {
            "workspace_path": str(workspace),
            "scope_id": "sub-1",
            "provider": provider,
        },
    )


def run_scope_resource_ids(lister: FakeLister, workspace: Path) -> dict[str, Any]:
    with client_with() as client:
        with patch.object(ScopeDiscovery, "_lister", return_value=lister):
            return post_scope_resource_ids(client, workspace, "azurerm")


@pytest.mark.parametrize("endpoint", IMPORT_ENDPOINTS)
def test_import_endpoints_require_token_when_configured(endpoint: str) -> None:
    """The 501 stubs answered before every submit-time check; the
    implementations sit behind the same bearer dependency as the rest."""
    with client_with(token="expected") as client:
        response = client.post(
            endpoint,
            json={"workspace_path": "/tmp/does-not-exist", **EXTRA[endpoint]},
        )
    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/problem+json")


@pytest.mark.parametrize("endpoint", IMPORT_ENDPOINTS)
def test_import_endpoints_404_on_a_missing_workspace(endpoint: str) -> None:
    """All three take a workspace, so a well-formed body against a
    nonexistent one is a synchronous 404 and no job."""
    with client_with() as client:
        response = client.post(
            endpoint,
            json={"workspace_path": "/tmp/does-not-exist", **EXTRA[endpoint]},
        )
    assert response.status_code == 404
    assert "location" not in response.headers


def test_import_forwards_the_address_resource_id_and_env(tmp_path: Path) -> None:
    """`import` is a pass-through like `apply`: argv carries the address
    and the resource ID, the environment carries the request's env."""
    workspace = tmp_path / "ws"
    workspace.mkdir()

    ok = CommandResult(ok=True, stdout="Import successful!", stderr="", exit_code=0)
    with client_with() as client:
        with patch(
            "src.engine.IacEngine.import_resource",
            new_callable=AsyncMock,
            return_value=ok,
        ) as mock:
            body = submit_and_poll(
                client,
                "/v1/import",
                {
                    "workspace_path": str(workspace),
                    "address": "google_storage_bucket.assets",
                    "resource_id": "my-assets",
                    "env": {"GOOGLE_PROJECT": "proj-1"},
                },
            )
    assert body["status"] == "succeeded"
    assert body["result"]["stdout"] == "Import successful!"
    mock.assert_awaited_once_with(
        workspace,
        "google_storage_bucket.assets",
        "my-assets",
        {"GOOGLE_PROJECT": "proj-1"},
        [],
        {},
    )


def test_state_resource_ids_answers_a_json_array_of_managed_ids(
    tmp_path: Path,
) -> None:
    """On exit 0 `stdout` is the JSON array the contract promises, with
    data sources left out, and whatever the engine wrote to `stderr`
    still reaches the caller."""
    workspace = tmp_path / "ws"
    workspace.mkdir()

    body = run_state_resource_ids(
        CommandResult(
            ok=True,
            stdout=STATE_DOCUMENT,
            stderr="Acquiring state lock. This may take a few moments...",
            exit_code=0,
        ),
        workspace,
    )

    assert body["status"] == "succeeded"
    assert body["kind"] == "state_resource_ids"
    assert body["result"]["exit_code"] == 0
    assert json.loads(body["result"]["stdout"]) == [
        "/subscriptions/s/resourceGroups/rg"
    ]
    assert body["result"]["stderr"] == (
        "Acquiring state lock. This may take a few moments..."
    )


def test_state_resource_ids_reports_an_unparsable_state(tmp_path: Path) -> None:
    """A successful `state pull` whose output is not a state document is
    an engine-plane failure, not a silently empty list."""
    workspace = tmp_path / "ws"
    workspace.mkdir()

    body = run_state_resource_ids(
        CommandResult(ok=True, stdout="not a state document", stderr="", exit_code=0),
        workspace,
    )

    assert body["status"] == "succeeded"
    assert body["result"]["exit_code"] == 1
    assert body["result"]["stdout"] == ""
    assert "unparsable state document" in body["result"]["stderr"]


def test_state_resource_ids_passes_an_engine_failure_through(tmp_path: Path) -> None:
    """A failed `state pull` keeps its own exit code and stderr, and
    reports no IDs."""
    workspace = tmp_path / "ws"
    workspace.mkdir()

    body = run_state_resource_ids(
        CommandResult(
            ok=False,
            stdout="partial output",
            stderr="Error: Backend initialization required",
            exit_code=1,
        ),
        workspace,
    )

    assert body["status"] == "succeeded"
    assert body["result"]["exit_code"] == 1
    assert body["result"]["stdout"] == ""
    assert "Backend initialization required" in body["result"]["stderr"]


def test_state_resource_ids_fails_the_job_on_an_unexpected_reader_error(
    tmp_path: Path,
) -> None:
    """Only StateReadError is an engine-plane failure. Any other error out
    of the reader is a service fault, so the job ends `failed` with a
    Problem instead of a `succeeded` job reporting exit 1."""
    workspace = tmp_path / "ws"
    workspace.mkdir()

    with patch.object(
        StateResourceIds, "read", side_effect=ValueError("reader exploded")
    ):
        body = run_state_resource_ids(
            CommandResult(ok=True, stdout=STATE_DOCUMENT, stderr="", exit_code=0),
            workspace,
        )

    assert body["status"] == "failed"
    assert body["result"] is None
    assert body["error"]["status"] == 500
    assert "reader exploded" in body["error"]["detail"]


def test_scope_resource_ids_answers_a_deduplicated_json_array(tmp_path: Path) -> None:
    """The lister's IDs reach `stdout` as a JSON array, deduplicated in
    first-seen order, and the request's scope is what it was asked for."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    lister = FakeLister(
        ["/subscriptions/s/rg/b", "/subscriptions/s/rg/a", "/subscriptions/s/rg/b"]
    )

    body = run_scope_resource_ids(lister, workspace)

    assert body["status"] == "succeeded"
    assert body["kind"] == "scope_resource_ids"
    assert body["result"]["exit_code"] == 0
    assert json.loads(body["result"]["stdout"]) == [
        "/subscriptions/s/rg/b",
        "/subscriptions/s/rg/a",
    ]
    assert lister.scopes == ["sub-1"]


def test_scope_resource_ids_reports_a_discovery_failure(tmp_path: Path) -> None:
    """A cloud error is an engine-plane failure: exit 1, the cloud's own
    message in stderr, no IDs."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    lister = FakeLister(error=DiscoveryError("403 from Resource Graph: denied"))

    body = run_scope_resource_ids(lister, workspace)

    assert body["status"] == "succeeded"
    assert body["result"]["exit_code"] == 1
    assert body["result"]["stdout"] == ""
    assert body["result"]["stderr"] == "403 from Resource Graph: denied"


@pytest.mark.parametrize("provider", ["azurerm", "google", "aws"])
def test_scope_resource_ids_lists_with_the_providers_lister(
    provider: str, tmp_path: Path
) -> None:
    """The request's provider picks the lister, and its scope_id is what
    the lister is asked about."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    lister = FakeLister(["/a"])

    with client_with() as client:
        with patch.object(ScopeDiscovery, "_lister", return_value=lister) as dispatch:
            body = post_scope_resource_ids(client, workspace, provider)

    assert dispatch.call_args.args[0] == provider
    assert lister.scopes == ["sub-1"]
    assert body["result"]["stdout"] == '["/a"]'


def test_scope_resource_ids_refuses_a_malformed_scope(tmp_path: Path) -> None:
    """A scope_id that is not the shape its cloud names is refused by the
    lister itself: exit 1 on a `succeeded` job, never a 500 out of a URL
    the service built from it. No patching: this is the real dispatch,
    and it reaches no network."""
    workspace = tmp_path / "ws"
    workspace.mkdir()

    with client_with() as client:
        body = submit_and_poll(
            client,
            "/v1/import/scope-resource-ids",
            {
                "workspace_path": str(workspace),
                "scope_id": "../organizations/123456",
                "provider": "google",
            },
        )

    assert body["status"] == "succeeded"
    assert body["result"]["exit_code"] == 1
    assert body["result"]["stdout"] == ""
    assert "is not a GCP project id" in body["result"]["stderr"]


def test_scope_resource_ids_fails_the_job_on_an_unexpected_error(
    tmp_path: Path,
) -> None:
    """Only DiscoveryError is an engine-plane failure. Anything else is a
    service fault, so the job ends `failed` with a Problem."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    lister = FakeLister(error=RuntimeError("discovery exploded"))

    body = run_scope_resource_ids(lister, workspace)

    assert body["status"] == "failed"
    assert body["result"] is None
    assert body["error"]["status"] == 500
