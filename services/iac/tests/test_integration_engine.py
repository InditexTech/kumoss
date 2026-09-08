# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Real-engine integration test for the IaC service.

Unlike the unit suite (which patches every subprocess call), this test
drives the HTTP API end to end against a real engine binary:
init → validate → plan → show -json → apply → state pull, using the
hermetic ``terraform_data`` fixture (no provider downloads, no network,
no cloud credentials). It runs once per engine the image bundles —
OpenTofu (``tofu``) and Terraform — proving both work behind the same
service; each engine skips itself when its binary is not on PATH.

It is the only place ``engine._run`` streaming, the ``./`` plan-file
anchoring, the ``env=`` plumbing and ``-backend-config`` are exercised
against a real process, so keep it green when touching ``engine.py``.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from .test_api import _client_with, _poll_until_terminal

_FIXTURE = Path(__file__).parent / "fixtures" / "engine_smoke" / "main.tf"
_DEADLINE = 120.0  # real engine commands, generous but bounded

_BACKEND_BLOCK = """
terraform {
  backend "local" {}
}
"""
_BACKEND_STATE_PATH = "state/custom.tfstate"

ENGINES = [
    pytest.param(
        binary,
        marks=pytest.mark.skipif(
            shutil.which(binary) is None,
            reason=f"`{binary}` not on PATH; real-engine integration test skipped",
        ),
    )
    for binary in ("tofu", "terraform")
]


def _workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    shutil.copy(_FIXTURE, workspace / "main.tf")
    return workspace


def _runner(client: TestClient, workspace: Path):
    def run(endpoint: str, extra: dict | None = None) -> dict:
        response = client.post(
            endpoint,
            json={
                "workspace_path": str(workspace),
                "scope_id": "00000000-0000-0000-0000-000000000000",
                **(extra or {}),
            },
        )
        assert response.status_code == 202, response.text
        body = _poll_until_terminal(
            client, response.json()["job_id"], deadline=_DEADLINE
        )
        assert body["status"] == "succeeded", body
        result = body["result"]
        assert result["exit_code"] == 0, result["stderr"]
        return result

    return run


@pytest.mark.parametrize("binary", ENGINES)
def test_full_pipeline_with_real_engine(binary: str, tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)

    with _client_with(iac_binary=binary) as client:
        run = _runner(client, workspace)

        run("/v1/init")
        run("/v1/validate")
        run("/v1/plan", {"plan_file": "smoke.plan"})

        show = run("/v1/show", {"plan_file": "smoke.plan"})
        plan = json.loads(show["stdout"])
        # The core's drift parser rejects format_version >= 2.0; the
        # engine must stay on the 1.x plan representation.
        assert plan["format_version"].startswith("1."), plan["format_version"]
        actions = [
            change["change"]["actions"]
            for change in plan["resource_changes"]
            if change["address"] == "terraform_data.probe"
        ]
        assert actions == [["create"]]

        run("/v1/apply", {"plan_file": "smoke.plan"})

        state_ids = run("/v1/import/state-resource-ids")
        ids = json.loads(state_ids["stdout"])
        assert len(ids) == 1  # the applied terraform_data.probe instance


@pytest.mark.parametrize("binary", ENGINES)
def test_plan_file_with_leading_dash_is_a_file_not_a_flag(
    binary: str, tmp_path: Path
) -> None:
    """The contract allows plan-file names such as ``-x``; the ``./``
    anchoring must make the engine treat them as paths, not flags."""
    workspace = _workspace(tmp_path)

    with _client_with(iac_binary=binary) as client:
        run = _runner(client, workspace)
        run("/v1/init")
        run("/v1/plan", {"plan_file": "-destroy"})
        assert (workspace / "-destroy").is_file()
        show = run("/v1/show", {"plan_file": "-destroy"})
        assert json.loads(show["stdout"])["format_version"].startswith("1.")


@pytest.mark.parametrize("binary", ENGINES)
def test_init_honours_tf_backend_config(binary: str, tmp_path: Path) -> None:
    """``TF_BACKEND_CONFIG`` is passed to ``init`` as ``-backend-config``
    relative to the workspace. With a ``local`` backend the effect is
    directly observable: state lands at the configured ``path`` instead
    of the default ``terraform.tfstate``."""
    workspace = _workspace(tmp_path)
    with (workspace / "main.tf").open("a") as fh:
        fh.write(_BACKEND_BLOCK)
    (workspace / "backend.hcl").write_text(f'path = "{_BACKEND_STATE_PATH}"\n')

    with _client_with(iac_binary=binary, backend_config="backend.hcl") as client:
        run = _runner(client, workspace)
        run("/v1/init")
        run("/v1/plan", {"plan_file": "smoke.plan"})
        run("/v1/apply", {"plan_file": "smoke.plan"})

        assert (workspace / _BACKEND_STATE_PATH).is_file()
        assert not (workspace / "terraform.tfstate").exists()

        state_ids = run("/v1/import/state-resource-ids")
        assert len(json.loads(state_ids["stdout"])) == 1
