# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Argument assembly of the engine commands the import endpoints run."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

from src.engine import CommandResult, IacEngine, RunInputs
from src.models import ProviderScope


def test_import_resource_passes_address_id_and_scope_overlay() -> None:
    engine = IacEngine(binary="tofu")
    ok = CommandResult(ok=True, stdout="Import successful!", stderr="")
    with patch.object(
        IacEngine, "_run", new_callable=AsyncMock, return_value=ok
    ) as run:
        result = asyncio.run(
            engine.import_resource(
                Path("/ws"),
                "azurerm_resource_group.main",
                "/subscriptions/s/resourceGroups/rg",
                {"ARM_SUBSCRIPTION_ID": "s"},
            )
        )
    assert result is ok
    run.assert_awaited_once_with(
        [
            "import",
            "-no-color",
            "-input=false",
            "azurerm_resource_group.main",
            "/subscriptions/s/resourceGroups/rg",
        ],
        Path("/ws"),
        {"ARM_SUBSCRIPTION_ID": "s"},
    )


def test_scope_env_merges_every_pair_and_ignores_unknown_providers() -> None:
    engine = IacEngine(binary="tofu")
    env = engine.scope_env(
        [
            ProviderScope(provider="azurerm", scope_id="sub-1"),
            ProviderScope(provider="google", scope_id="proj-1"),
            ProviderScope(provider="aws", scope_id="123456789012"),
            ProviderScope(provider="oci", scope_id="ocid1.compartment.oc1..x"),
            ProviderScope(provider="kubernetes", scope_id="ns"),
            ProviderScope(provider="random", scope_id="r"),
        ]
    )
    assert env == {
        "ARM_SUBSCRIPTION_ID": "sub-1",
        "GOOGLE_PROJECT": "proj-1",
        "TF_VAR_aws_account_id": "123456789012",
        "TF_VAR_compartment_ocid": "ocid1.compartment.oc1..x",
    }


def test_scope_env_is_empty_without_scopes() -> None:
    assert IacEngine(binary="tofu").scope_env([]) == {}


def test_state_pull_runs_on_the_unmodified_environment() -> None:
    engine = IacEngine(binary="tofu")
    ok = CommandResult(ok=True, stdout="{}", stderr="")
    with patch.object(
        IacEngine, "_run", new_callable=AsyncMock, return_value=ok
    ) as run:
        result = asyncio.run(engine.state_pull(Path("/ws")))
    assert result is ok
    run.assert_awaited_once_with(["state", "pull"], Path("/ws"))


def test_plan_passes_var_files_then_a_temporary_values_file(tmp_path: Path) -> None:
    """Var files go first, in order; the values follow as one owner-only
    file outside the workspace, which is gone once the command ends."""
    import json
    import stat

    engine = IacEngine(binary="tofu")
    seen: dict[str, object] = {}

    async def fake_run(args: list[str], cwd: Path, env: dict[str, str] | None = None):
        values_arg = args[-1]
        assert values_arg.startswith("-var-file=")
        values_path = Path(values_arg.removeprefix("-var-file="))
        seen["args"] = args
        seen["path"] = values_path
        seen["mode"] = stat.S_IMODE(values_path.stat().st_mode)
        seen["content"] = json.loads(values_path.read_text())
        return CommandResult(ok=True, stdout="", stderr="")

    inputs = RunInputs(
        var_files=("envs/dev.tfvars", "b.tfvars.json"),
        variables={"region": {"location": "x"}, "pw": "s3cr3t"},
    )
    with patch.object(IacEngine, "_run", side_effect=fake_run):
        result = asyncio.run(engine.plan(tmp_path, ["module.a"], "p.plan", {}, inputs))

    assert result.ok
    args = seen["args"]
    assert isinstance(args, list)
    assert args[:-1] == [
        "plan",
        "-no-color",
        "-input=false",
        "-out",
        "p.plan",
        "-target",
        "module.a",
        "-var-file=envs/dev.tfvars",
        "-var-file=b.tfvars.json",
    ]
    path = seen["path"]
    assert isinstance(path, Path)
    assert not path.is_relative_to(tmp_path)
    assert seen["mode"] == 0o600
    assert seen["content"] == {"region": {"location": "x"}, "pw": "s3cr3t"}
    assert not path.exists()
    assert "s3cr3t" not in repr(inputs)


def test_values_file_is_removed_when_the_command_fails(tmp_path: Path) -> None:
    engine = IacEngine(binary="tofu")
    paths: list[Path] = []

    async def boom(args: list[str], cwd: Path, env: dict[str, str] | None = None):
        paths.append(Path(args[-1].removeprefix("-var-file=")))
        raise RuntimeError("engine crashed")

    with patch.object(IacEngine, "_run", side_effect=boom):
        try:
            asyncio.run(
                engine.plan(tmp_path, [], "p.plan", {}, RunInputs(variables={"a": 1}))
            )
        except RuntimeError:
            pass
    assert paths and not paths[0].exists()


def test_import_places_var_files_before_the_address_and_id(tmp_path: Path) -> None:
    engine = IacEngine(binary="tofu")
    ok = CommandResult(ok=True, stdout="", stderr="")
    with patch.object(
        IacEngine, "_run", new_callable=AsyncMock, return_value=ok
    ) as run:
        asyncio.run(
            engine.import_resource(
                tmp_path, "a.b", "id-1", {}, RunInputs(var_files=("x.tfvars",))
            )
        )
    run.assert_awaited_once_with(
        ["import", "-no-color", "-input=false", "-var-file=x.tfvars", "a.b", "id-1"],
        tmp_path,
        {},
    )


def test_var_file_symlinked_out_of_the_workspace_fails_the_command(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside.tfvars"
    _ = outside.write_text("x = 1")
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "link.tfvars").symlink_to(outside)

    engine = IacEngine(binary="tofu")
    with patch.object(IacEngine, "_run", new_callable=AsyncMock) as run:
        result = asyncio.run(
            engine.plan(
                workspace, [], "p.plan", {}, RunInputs(var_files=("link.tfvars",))
            )
        )
    run.assert_not_awaited()
    assert not result.ok
    assert result.exit_code == 1
    assert "outside the workspace" in result.stderr


def test_scope_bindings_win_over_var_files_and_values(tmp_path: Path) -> None:
    """A request's own inputs cannot retarget the command off its scope."""
    import json

    engine = IacEngine(binary="tofu")
    seen: dict[str, object] = {}

    async def fake_run(args: list[str], cwd: Path, env: dict[str, str] | None = None):
        seen["args"] = args
        seen["content"] = json.loads(
            Path(args[-1].removeprefix("-var-file=")).read_text()
        )
        return CommandResult(ok=True, stdout="", stderr="")

    env = engine.scope_env("oci", "ocid1.compartment.authorized")
    inputs = RunInputs(
        var_files=("envs/other.tfvars",),
        variables={"compartment_ocid": "ocid1.compartment.other", "name": "x"},
    )
    with patch.object(IacEngine, "_run", side_effect=fake_run):
        _ = asyncio.run(engine.plan(tmp_path, [], "p.plan", env, inputs))

    args = seen["args"]
    assert isinstance(args, list)
    assert args[-2] == "-var-file=envs/other.tfvars"
    assert seen["content"] == {
        "compartment_ocid": "ocid1.compartment.authorized",
        "name": "x",
    }


def test_no_values_file_without_inputs(tmp_path: Path) -> None:
    engine = IacEngine(binary="tofu")
    ok = CommandResult(ok=True, stdout="", stderr="")
    env = engine.scope_env("aws", "123456789012")
    with patch.object(
        IacEngine, "_run", new_callable=AsyncMock, return_value=ok
    ) as run:
        _ = asyncio.run(engine.plan(tmp_path, [], "p.plan", env, RunInputs()))
    run.assert_awaited_once_with(
        ["plan", "-no-color", "-input=false", "-out", "p.plan"], tmp_path, env
    )
