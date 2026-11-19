# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the IaC reference implementation.

These cover the contract surface: healthz, auth, request validation
(including the `plan_file` path-traversal guard, the optional
`scopes` list accepted on `init`, `plan`, `apply` and `import` and
rejected everywhere else, and the `provider` / `scope_id` pair of
scope discovery), per-provider scope injection into the engine
environment, the 404-on-missing-workspace path,
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
from src.engine import CommandResult, RunInputs
from src.discovery import ScopeDiscovery
from src.discovery._aws import AwsScopeLister
from src.exceptions import DiscoveryError
from src.state import StateResourceIds


SCOPE: dict[str, Any] = {
    "scopes": [{"provider": "azurerm", "scope_id": "sub-uuid-1234"}]
}
DISCOVERY_SCOPE: dict[str, Any] = {"scope_id": "sub-uuid-1234", "provider": "azurerm"}

# (endpoint, engine method to stub, the body fields besides
# workspace_path that the endpoint documents)
OPERATIONS: list[tuple[str, str, dict[str, Any]]] = [
    ("/v1/init", "src.engine.IacEngine.init", {**SCOPE}),
    ("/v1/validate", "src.engine.IacEngine.validate", {}),
    ("/v1/plan", "src.engine.IacEngine.plan", {"plan_file": "x.plan", **SCOPE}),
    ("/v1/show", "src.engine.IacEngine.show_plan_json", {"plan_file": "x.plan"}),
    ("/v1/apply", "src.engine.IacEngine.apply", {"plan_file": "x.plan", **SCOPE}),
    (
        "/v1/import",
        "src.engine.IacEngine.import_resource",
        {
            "address": "azurerm_resource_group.main",
            "resource_id": "/subscriptions/x/resourceGroups/y",
            **SCOPE,
        },
    ),
]

EXTRA: dict[str, dict[str, Any]] = {
    endpoint: extra for endpoint, _, extra in OPERATIONS
} | {
    "/v1/import/state-resource-ids": {},
    "/v1/import/scope-resource-ids": {**DISCOVERY_SCOPE},
}

# The commands that take the optional `scopes` list.
SCOPED_ENDPOINTS: list[str] = [
    "/v1/init",
    "/v1/plan",
    "/v1/apply",
    "/v1/import",
]

# (endpoint, engine method to stub, extra request fields, expected
# engine args after the workspace) for the endpoints that take no
# scope.
UNSCOPED_OPERATIONS: list[tuple[str, str, dict[str, str], tuple[object, ...]]] = [
    ("/v1/validate", "src.engine.IacEngine.validate", {}, ()),
    (
        "/v1/show",
        "src.engine.IacEngine.show_plan_json",
        {"plan_file": "x.plan"},
        ("x.plan",),
    ),
    ("/v1/import/state-resource-ids", "src.engine.IacEngine.state_pull", {}, ()),
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
            json={"workspace_path": "/tmp/anywhere", **SCOPE},
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
            json={"workspace_path": str(tmp_path / "does-not-exist"), **SCOPE},
        )
    assert response.status_code == 404


def test_init_request_validation_returns_problem_json() -> None:
    with client_with() as client:
        response = client.post(
            "/v1/init",
            json={"workspace_path": "", **SCOPE},
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
                **SCOPE,
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
                json={"workspace_path": str(workspace), **SCOPE},
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
                "/v1/init", json={"workspace_path": str(workspace), **SCOPE}
            ).json()["job_id"]
            second: str = client.post(
                "/v1/init", json={"workspace_path": str(workspace), **SCOPE}
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
            "src.engine.IacEngine.plan", new_callable=AsyncMock, return_value=ok
        ) as plan_mock:
            response = client.post(
                "/v1/plan",
                json={
                    "workspace_path": str(workspace),
                    "targets": ["module.db"],
                    "plan_file": "abc123.plan",
                    **SCOPE,
                },
            )
            assert response.status_code == 202
            accepted: dict[str, str] = response.json()
            body = poll_until_terminal(client, accepted["job_id"])
    assert body["status"] == "succeeded"
    assert body["result"]["exit_code"] == 0
    plan_mock.assert_awaited_once_with(
        workspace,
        ["module.db"],
        "abc123.plan",
        {"ARM_SUBSCRIPTION_ID": "sub-uuid-1234"},
        RunInputs(),
    )


def test_plan_forwards_var_files_and_variables(tmp_path: Path) -> None:
    """`var_files` and `variables` reach the engine untouched; nothing
    else interprets them."""
    workspace = tmp_path / "ws"
    workspace.mkdir()

    ok = CommandResult(ok=True, stdout="", stderr="", exit_code=0)
    with client_with() as client:
        with patch(
            "src.engine.IacEngine.plan", new_callable=AsyncMock, return_value=ok
        ) as plan_mock:
            body = submit_and_poll(
                client,
                "/v1/plan",
                {
                    "workspace_path": str(workspace),
                    "plan_file": "abc123.plan",
                    "var_files": ["envs/dev.tfvars", "b.tfvars.json"],
                    "variables": {"region": {"location": "westeurope"}, "pw": "s3cr3t"},
                    **SCOPE,
                },
            )
    assert body["status"] == "succeeded"
    inputs = plan_mock.await_args.args[4]
    assert inputs == RunInputs(
        var_files=("envs/dev.tfvars", "b.tfvars.json"),
        variables={"region": {"location": "westeurope"}, "pw": "s3cr3t"},
    )


@pytest.mark.parametrize(
    "var_file",
    [
        "../x.tfvars",
        "/etc/x.tfvars",
        ".hidden/x.tfvars",
        "a/./x.tfvars",
        "x.txt",
        "x.tfvars.bak",
    ],
)
@pytest.mark.parametrize("endpoint", ["/v1/plan", "/v1/import"])
def test_var_files_cannot_escape_the_workspace(endpoint: str, var_file: str) -> None:
    with client_with() as client:
        response = client.post(
            endpoint,
            json={
                "workspace_path": "/tmp",
                **EXTRA[endpoint],
                **SCOPE,
                "var_files": [var_file],
            },
        )
    assert response.status_code == 422


def test_rejected_variables_are_not_echoed() -> None:
    """A 422 names the offending field, never the submitted values."""
    with client_with() as client:
        response = client.post(
            "/v1/plan",
            json={
                "workspace_path": "/tmp",
                "plan_file": "x.plan",
                **SCOPE,
                "variables": {"not a name": "s3cr3t-value"},
            },
        )
    assert response.status_code == 422
    assert "s3cr3t-value" not in response.text
    assert "variables" in response.text


@pytest.mark.parametrize(
    "endpoint", ["/v1/init", "/v1/validate", "/v1/show", "/v1/apply"]
)
def test_only_plan_and_import_take_variables(endpoint: str) -> None:
    with client_with() as client:
        response = client.post(
            endpoint,
            json={
                "workspace_path": "/tmp",
                **EXTRA.get(endpoint, {}),
                **({} if endpoint in ("/v1/validate", "/v1/show") else SCOPE),
                "variables": {"a": 1},
            },
        )
    assert response.status_code == 422


def test_init_invokes_engine_with_the_injected_scope(tmp_path: Path) -> None:
    """init reaches the cloud API, so the job runs with the request's
    scope_id in the engine's environment."""
    workspace = tmp_path / "ws"
    workspace.mkdir()

    ok = CommandResult(ok=True, stdout="has been initialized", stderr="")
    with client_with() as client:
        with patch(
            "src.engine.IacEngine.init", new_callable=AsyncMock, return_value=ok
        ) as init_mock:
            response = client.post(
                "/v1/init",
                json={"workspace_path": str(workspace), **SCOPE},
            )
            assert response.status_code == 202
            accepted: dict[str, str] = response.json()
            body = poll_until_terminal(client, accepted["job_id"])
    assert body["status"] == "succeeded"
    assert body["result"]["exit_code"] == 0
    init_mock.assert_awaited_once_with(
        workspace, {"ARM_SUBSCRIPTION_ID": "sub-uuid-1234"}
    )


def _init_argv(client: TestClient, workspace: Path) -> list[str]:
    """Submit an init job with the engine subprocess stubbed, and return
    the argv the engine wrapper assembled."""
    ok = CommandResult(ok=True, stdout="has been initialized", stderr="")
    with patch(
        "src.engine.IacEngine._run", new_callable=AsyncMock, return_value=ok
    ) as run:
        response = client.post(
            "/v1/init", json={"workspace_path": str(workspace), **SCOPE}
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
                "/v1/init", json={"workspace_path": str(workspace), **SCOPE}
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
                json={"workspace_path": str(workspace), **SCOPE},
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
                json={"workspace_path": str(workspace), **SCOPE},
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


@pytest.mark.parametrize("endpoint", SCOPED_ENDPOINTS)
@pytest.mark.parametrize(
    "scopes",
    [
        pytest.param(None, id="omitted"),
        pytest.param([], id="empty"),
        pytest.param(
            [
                {"provider": "azurerm", "scope_id": "s"},
                {"provider": "kubernetes", "scope_id": "ns"},
                {"provider": "random", "scope_id": "x"},
            ],
            id="several-providers",
        ),
    ],
)
def test_scoped_endpoints_take_scopes_optionally(
    endpoint: str, scopes: list[dict[str, str]] | None
) -> None:
    """`scopes` is optional, may be empty, and names any provider: the
    only thing wrong here is the nonexistent workspace, so 404 not 422."""
    body: dict[str, object] = {
        "workspace_path": "/tmp/does-not-exist",
        **EXTRA[endpoint],
    }
    del body["scopes"]
    if scopes is not None:
        body["scopes"] = scopes

    with client_with() as client:
        response = client.post(endpoint, json=body)
    assert response.status_code == 404


@pytest.mark.parametrize("endpoint", SCOPED_ENDPOINTS)
@pytest.mark.parametrize(
    "scopes",
    [
        pytest.param([{"provider": "azurerm", "scope_id": ""}], id="scope_id-empty"),
        pytest.param([{"provider": "azurerm"}], id="scope_id-missing"),
        pytest.param([{"scope_id": "s"}], id="provider-missing"),
        pytest.param(
            [{"provider": "AzureRM", "scope_id": "s"}], id="provider-uppercase"
        ),
        pytest.param(
            [{"provider": "hashicorp/azurerm", "scope_id": "s"}], id="provider-source"
        ),
        pytest.param([{"provider": "", "scope_id": "s"}], id="provider-empty"),
        pytest.param(
            [{"provider": "azurerm", "scope_id": "s", "region": "x"}],
            id="extra-field",
        ),
        pytest.param(
            [
                {"provider": "azurerm", "scope_id": "s-1"},
                {"provider": "azurerm", "scope_id": "s-2"},
            ],
            id="duplicate-provider",
        ),
        pytest.param(
            [{"provider": f"p{i}", "scope_id": "s"} for i in range(65)],
            id="too-many",
        ),
        pytest.param({"provider": "azurerm", "scope_id": "s"}, id="not-a-list"),
    ],
)
def test_scoped_endpoints_reject_malformed_scopes(
    endpoint: str, scopes: object
) -> None:
    """Each pair is typed: a non-Terraform provider name, an empty
    scope_id, an unknown key or the same provider twice is a 422."""
    body: dict[str, object] = {
        "workspace_path": "/tmp",
        **EXTRA[endpoint],
        "scopes": scopes,
    }

    with client_with() as client:
        response = client.post(endpoint, json=body)
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")


def test_a_duplicate_provider_is_named_in_the_422() -> None:
    with client_with() as client:
        response = client.post(
            "/v1/init",
            json={
                "workspace_path": "/tmp",
                "scopes": [
                    {"provider": "aws", "scope_id": "123456789012"},
                    {"provider": "aws", "scope_id": "210987654321"},
                ],
            },
        )
    assert response.status_code == 422
    assert "'aws' appears more than once" in response.json()["detail"]


@pytest.mark.parametrize(
    "field",
    [
        pytest.param({"scopes": []}, id="scopes-empty"),
        pytest.param(SCOPE, id="scopes"),
        pytest.param({"scope_id": "s"}, id="scope_id"),
        pytest.param({"provider": "azurerm"}, id="provider"),
        pytest.param({"terraform_provider": "azure"}, id="terraform_provider"),
    ],
)
@pytest.mark.parametrize(
    ("endpoint", "extra"),
    [(endpoint, extra) for endpoint, _, extra, _ in UNSCOPED_OPERATIONS],
)
def test_unscoped_endpoints_reject_a_scope(
    endpoint: str, extra: dict[str, str], field: dict[str, Any]
) -> None:
    """validate, show and state-resource-ids declare no scope, so sending
    `scopes` (even empty) or a 1.x scope field is an unknown field — 422,
    not silently ignored."""
    body: dict[str, object] = {"workspace_path": "/tmp", **extra, **field}

    with client_with() as client:
        response = client.post(endpoint, json=body)
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")


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


@pytest.mark.parametrize(
    ("endpoint", "engine_target", "extra", "tail"), UNSCOPED_OPERATIONS
)
def test_unscoped_endpoints_run_unscoped(
    endpoint: str,
    engine_target: str,
    extra: dict[str, str],
    tail: tuple[object, ...],
    tmp_path: Path,
) -> None:
    """validate, show and state-resource-ids take no scope: the
    engine is called with no environment overlay at all."""
    workspace = tmp_path / "ws"
    workspace.mkdir()

    ok = CommandResult(ok=True, stdout="", stderr="", exit_code=0)
    with client_with() as client:
        with patch(engine_target, new_callable=AsyncMock, return_value=ok) as mock:
            response = client.post(
                endpoint,
                json={"workspace_path": str(workspace), **extra},
            )
            assert response.status_code == 202
            accepted: dict[str, str] = response.json()
            _ = poll_until_terminal(client, accepted["job_id"])
    mock.assert_awaited_once_with(workspace, *tail)


def run_plan(workspace: Path, scopes: list[dict[str, str]] | None) -> AsyncMock:
    """Submit a plan with ``scopes`` (omitted when None), verification
    stubbed out, and return the engine mock once the job ended."""
    body: dict[str, object] = {"workspace_path": str(workspace), "plan_file": "x.plan"}
    if scopes is not None:
        body["scopes"] = scopes
    ok = CommandResult(ok=True, stdout="", stderr="", exit_code=0)
    with client_with() as client:
        with (
            patch.object(ScopeDiscovery, "verify_scope", new_callable=AsyncMock),
            patch(
                "src.engine.IacEngine.plan", new_callable=AsyncMock, return_value=ok
            ) as plan_mock,
        ):
            _ = submit_and_poll(client, "/v1/plan", body)
    return plan_mock


@pytest.mark.parametrize(
    ("provider", "expected"),
    [
        ("azurerm", {"ARM_SUBSCRIPTION_ID": "scope-1"}),
        ("google", {"GOOGLE_PROJECT": "scope-1"}),
        ("aws", {"TF_VAR_aws_account_id": "scope-1"}),
        ("oci", {"TF_VAR_compartment_ocid": "scope-1"}),
        ("kubernetes", {}),
        ("vsphere", {}),
        ("random", {}),
        ("azure", {}),
        ("gcp", {}),
    ],
)
def test_scope_is_injected_per_provider(
    provider: str, expected: dict[str, str], tmp_path: Path
) -> None:
    """A pair's scope_id reaches the engine as the environment overlay
    its provider selects, and only where that provider has a variable
    naming a scope: a provider-level one for azurerm and google, an
    input variable the generated code declares for oci
    (compartment_ocid) and aws (aws_account_id). Any other provider is
    accepted and ignored, including the 1.x cloud names."""
    workspace = tmp_path / "ws"
    workspace.mkdir()

    plan_mock = run_plan(workspace, [{"provider": provider, "scope_id": "scope-1"}])

    plan_mock.assert_awaited_once_with(workspace, [], "x.plan", expected, RunInputs())


def test_several_scopes_are_merged_into_one_overlay(tmp_path: Path) -> None:
    """A module using several providers gets every pair injected at once;
    pairs for providers without a variable add nothing."""
    workspace = tmp_path / "ws"
    workspace.mkdir()

    plan_mock = run_plan(
        workspace,
        [
            {"provider": "azurerm", "scope_id": "sub-1"},
            {"provider": "kubernetes", "scope_id": "ns-1"},
            {"provider": "google", "scope_id": "proj-1"},
            {"provider": "aws", "scope_id": "123456789012"},
            {"provider": "oci", "scope_id": "ocid1.compartment.oc1..x"},
        ],
    )

    plan_mock.assert_awaited_once_with(
        workspace,
        [],
        "x.plan",
        {
            "ARM_SUBSCRIPTION_ID": "sub-1",
            "GOOGLE_PROJECT": "proj-1",
            "TF_VAR_aws_account_id": "123456789012",
            "TF_VAR_compartment_ocid": "ocid1.compartment.oc1..x",
        },
        RunInputs(),
    )


@pytest.mark.parametrize("scopes", [None, []], ids=["omitted", "empty"])
def test_no_scopes_inject_nothing(
    scopes: list[dict[str, str]] | None, tmp_path: Path
) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()

    plan_mock = run_plan(workspace, scopes)

    plan_mock.assert_awaited_once_with(workspace, [], "x.plan", {}, RunInputs())


@pytest.mark.parametrize(
    ("endpoint", "engine_target", "extra"),
    [op for op in OPERATIONS if "scopes" in op[2]],
)
def test_a_scope_the_credentials_cannot_serve_never_reaches_the_engine(
    endpoint: str, engine_target: str, extra: dict[str, Any], tmp_path: Path
) -> None:
    """No variable points an AWS command at an account, so init, plan,
    apply and import first check the credentials belong to the aws
    pair's scope_id. A mismatch ends the command with exit code 1 and
    the reason, and the engine is never started."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    body: dict[str, object] = {
        "workspace_path": str(workspace),
        **extra,
        "scopes": [{"provider": "aws", "scope_id": "123456789012"}],
    }
    refused = DiscoveryError("AWS credentials belong to account 999, not 123456789012")

    with client_with() as client:
        with (
            patch.object(
                ScopeDiscovery,
                "verify_scope",
                new_callable=AsyncMock,
                side_effect=refused,
            ) as verify_mock,
            patch(engine_target, new_callable=AsyncMock) as engine_mock,
        ):
            job = submit_and_poll(client, endpoint, body)

    verify_mock.assert_awaited_once_with("aws", "123456789012")
    engine_mock.assert_not_awaited()
    assert job["status"] == "succeeded"
    assert job["result"]["exit_code"] == 1
    assert "belong to account 999" in job["result"]["stderr"]


def test_every_pair_is_verified_before_the_engine_starts(tmp_path: Path) -> None:
    """verify_scope runs once per pair, in order; the real dispatch then
    asks STS only for the aws pair and lets the engine run."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    scopes = [
        {"provider": "azurerm", "scope_id": "sub-1"},
        {"provider": "aws", "scope_id": "123456789012"},
        {"provider": "kubernetes", "scope_id": "ns-1"},
    ]
    ok = CommandResult(ok=True, stdout="", stderr="", exit_code=0)

    with client_with() as client:
        with (
            patch.object(
                ScopeDiscovery,
                "verify_scope",
                autospec=True,
                side_effect=ScopeDiscovery.verify_scope,
            ) as verify_mock,
            patch.object(
                AwsScopeLister, "verify_account", new_callable=AsyncMock
            ) as sts_mock,
            patch(
                "src.engine.IacEngine.apply", new_callable=AsyncMock, return_value=ok
            ) as apply_mock,
        ):
            job = submit_and_poll(
                client,
                "/v1/apply",
                {
                    "workspace_path": str(workspace),
                    "plan_file": "x.plan",
                    "scopes": scopes,
                },
            )

    assert [c.args[1:] for c in verify_mock.await_args_list] == [
        (s["provider"], s["scope_id"]) for s in scopes
    ]
    sts_mock.assert_awaited_once_with("123456789012")
    apply_mock.assert_awaited_once()
    assert job["result"]["exit_code"] == 0


def test_a_refused_aws_pair_stops_the_command_among_others(tmp_path: Path) -> None:
    """The STS check applies per pair: an aws pair the credentials do
    not own refuses the command even when other pairs are fine."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    refused = DiscoveryError("AWS credentials belong to account 999, not 123456789012")

    with client_with() as client:
        with (
            patch.object(
                AwsScopeLister,
                "verify_account",
                new_callable=AsyncMock,
                side_effect=refused,
            ) as sts_mock,
            patch("src.engine.IacEngine.init", new_callable=AsyncMock) as init_mock,
        ):
            job = submit_and_poll(
                client,
                "/v1/init",
                {
                    "workspace_path": str(workspace),
                    "scopes": [
                        {"provider": "google", "scope_id": "proj-1"},
                        {"provider": "aws", "scope_id": "123456789012"},
                    ],
                },
            )

    sts_mock.assert_awaited_once_with("123456789012")
    init_mock.assert_not_awaited()
    assert job["result"]["exit_code"] == 1
    assert "belong to account 999" in job["result"]["stderr"]


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


def test_import_forwards_the_address_resource_id_and_scope(tmp_path: Path) -> None:
    """`import` is a pass-through like `apply`: argv carries the address
    and the resource ID, the environment carries the scope overlay."""
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
                    "scopes": [{"provider": "google", "scope_id": "proj-1"}],
                },
            )
    assert body["status"] == "succeeded"
    assert body["result"]["stdout"] == "Import successful!"
    mock.assert_awaited_once_with(
        workspace,
        "google_storage_bucket.assets",
        "my-assets",
        {"GOOGLE_PROJECT": "proj-1"},
        RunInputs(),
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
