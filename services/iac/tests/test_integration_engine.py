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
from typing import Any

import pytest

from .test_api import client_with, poll_until_terminal

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
    _ = shutil.copy(_FIXTURE, workspace / "main.tf")

    with client_with(iac_binary=binary) as client:

        def run(endpoint: str, extra: dict[str, str] | None = None) -> dict[str, Any]:
            response = client.post(
                endpoint, json={"workspace_path": str(workspace), **(extra or {})}
            )
            assert response.status_code == 202, response.text
            accepted: dict[str, str] = response.json()
            body = poll_until_terminal(client, accepted["job_id"], deadline=_DEADLINE)
            assert body["status"] == "succeeded", body
            result: dict[str, Any] = body["result"]
            assert result["exit_code"] == 0, result["stderr"]
            return result

        _ = run("/v1/init")
        _ = run("/v1/validate")
        _ = run("/v1/plan", {"plan_file": "smoke.plan"})

        show = run("/v1/show", {"plan_file": "smoke.plan"})
        stdout: str = show["stdout"]
        plan: dict[str, Any] = json.loads(stdout)
        # The core's drift parser rejects format_version >= 2.0; the
        # engine must stay on the 1.x plan representation.
        format_version: str = plan["format_version"]
        assert format_version.startswith("1."), format_version
        changes: list[dict[str, Any]] = plan["resource_changes"]
        actions = [
            change["change"]["actions"]
            for change in changes
            if change["address"] == "terraform_data.probe"
        ]
        assert actions == [["create"]]

        _ = run("/v1/apply", {"plan_file": "smoke.plan"})
