# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Real-engine integration test for the IaC service.

Unlike the unit suite (which patches every subprocess call), this test
drives the HTTP API end to end against a real engine binary:
init → validate → plan → show -json → apply, using the hermetic
``terraform_data`` fixture (no provider downloads, no network,
no cloud credentials). It runs once per engine the image bundles —
OpenTofu (``tofu``) and Terraform — proving both work behind the same
service; each engine skips itself when its binary is not on PATH.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from .test_api import _client_with, _poll_until_terminal

_FIXTURE = Path(__file__).parent / "fixtures" / "engine_smoke" / "main.tf"
_DEADLINE = 120.0  # real engine commands, generous but bounded


def _engine(binary: str) -> object:
    return pytest.param(
        binary,
        marks=pytest.mark.skipif(
            shutil.which(binary) is None,
            reason=f"`{binary}` not on PATH; real-engine integration test skipped",
        ),
    )


@pytest.mark.parametrize("binary", [_engine("tofu"), _engine("terraform")])
def test_full_pipeline_with_real_engine(binary: str, tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    shutil.copy(_FIXTURE, workspace / "main.tf")

    with _client_with(iac_binary=binary) as client:

        def run(endpoint: str, extra: dict | None = None) -> dict:
            response = client.post(
                endpoint, json={"workspace_path": str(workspace), **(extra or {})}
            )
            assert response.status_code == 202, response.text
            body = _poll_until_terminal(
                client, response.json()["job_id"], deadline=_DEADLINE
            )
            assert body["status"] == "succeeded", body
            result = body["result"]
            assert result["exit_code"] == 0, result["stderr"]
            return result

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
