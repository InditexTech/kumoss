# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Argument and environment assembly of the engine commands."""

from __future__ import annotations

import asyncio
import json
import logging
import stat
from pathlib import Path
from collections.abc import Awaitable, Mapping
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from src.engine import CommandResult, IacEngine

OK = CommandResult(ok=True, stdout="", stderr="")
ENV = {"ARM_SUBSCRIPTION_ID": "sub-1"}


def test_import_resource_passes_address_id_and_env() -> None:
    engine = IacEngine(binary="tofu")
    with patch.object(
        IacEngine, "_run", new_callable=AsyncMock, return_value=OK
    ) as run:
        result = asyncio.run(
            engine.import_resource(
                Path("/ws"),
                "azurerm_resource_group.main",
                "/subscriptions/s/resourceGroups/rg",
                ENV,
                {},
            )
        )
    assert result is OK
    run.assert_awaited_once_with(
        [
            "import",
            "-no-color",
            "-input=false",
            "azurerm_resource_group.main",
            "/subscriptions/s/resourceGroups/rg",
        ],
        Path("/ws"),
        ENV,
    )


def test_state_pull_runs_on_the_unmodified_environment() -> None:
    engine = IacEngine(binary="tofu")
    with patch.object(
        IacEngine, "_run", new_callable=AsyncMock, return_value=OK
    ) as run:
        result = asyncio.run(engine.state_pull(Path("/ws")))
    assert result is OK
    run.assert_awaited_once_with(["state", "pull"], Path("/ws"))


def _commands(engine: IacEngine) -> list[tuple[Awaitable[CommandResult], list[str]]]:
    """Each env-taking command with ENV, and the argv it must run."""
    ws = Path("/ws")
    return [
        (
            engine.init(ws, ENV),
            ["init", "-no-color", "-input=false", "-reconfigure"],
        ),
        (engine.validate(ws, ENV), ["validate", "-no-color"]),
        (
            engine.show_plan_json(ws, "p.plan", ENV),
            ["show", "-json", "-no-color", "p.plan"],
        ),
        (
            engine.apply(ws, "p.plan", ENV),
            ["apply", "-no-color", "-input=false", "-auto-approve", "p.plan"],
        ),
        (
            engine.plan(ws, [], "p.plan", ENV, {}),
            ["plan", "-no-color", "-input=false", "-out", "p.plan"],
        ),
    ]


def test_every_command_runs_with_the_request_env() -> None:
    engine = IacEngine(binary="tofu")

    async def run_all() -> None:
        for command, args in _commands(engine):
            with patch.object(
                IacEngine, "_run", new_callable=AsyncMock, return_value=OK
            ) as run:
                _ = await command
            run.assert_awaited_once_with(args, Path("/ws"), ENV)

    asyncio.run(run_all())


def test_env_is_added_to_the_service_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The subprocess sees both the service's own variables and the request's."""
    monkeypatch.setenv("IAC_TEST_AMBIENT", "ambient")
    script = tmp_path / "engine.sh"
    _ = script.write_text('#!/bin/sh\necho "$IAC_TEST_AMBIENT $ARM_SUBSCRIPTION_ID"\n')
    script.chmod(0o755)
    result = asyncio.run(IacEngine(binary=str(script)).validate(tmp_path, ENV))
    assert result.ok
    assert result.stdout.strip() == "ambient sub-1"


def test_env_values_are_never_logged(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    script = tmp_path / "engine.sh"
    _ = script.write_text("#!/bin/sh\nexit 0\n")
    script.chmod(0o755)
    with caplog.at_level(logging.INFO, logger="iac.engine"):
        _ = asyncio.run(
            IacEngine(binary=str(script)).validate(tmp_path, {"SECRET_X": "s3cr3t"})
        )
    assert "SECRET_X" in caplog.text
    assert "s3cr3t" not in caplog.text


def test_plan_passes_vars_as_the_last_var_file(tmp_path: Path) -> None:
    """The values go in one owner-only file outside the workspace, passed
    last, which is gone once the command ends."""
    engine = IacEngine(binary="tofu")
    seen: dict[str, Any] = {}

    async def fake_run(
        args: list[str], _cwd: Path, _env: Mapping[str, str] | None = None
    ) -> CommandResult:
        values_path = Path(args[-1].removeprefix("-var-file="))
        seen["args"] = args
        seen["path"] = values_path
        seen["mode"] = stat.S_IMODE(values_path.stat().st_mode)
        seen["content"] = json.loads(values_path.read_text())
        return OK

    variables = {"region": {"location": "x"}, "pw": "s3cr3t"}
    with patch.object(IacEngine, "_run", side_effect=fake_run):
        result = asyncio.run(
            engine.plan(tmp_path, ["module.a"], "p.plan", {}, variables)
        )

    assert result.ok
    assert seen["args"][:-1] == [
        "plan",
        "-no-color",
        "-input=false",
        "-out",
        "p.plan",
        "-target",
        "module.a",
    ]
    assert seen["args"][-1].startswith("-var-file=")
    path: Path = seen["path"]
    assert not path.is_relative_to(tmp_path)
    assert seen["mode"] == 0o600
    assert seen["content"] == variables
    assert not path.exists()


def test_vars_file_is_removed_when_the_command_fails(tmp_path: Path) -> None:
    engine = IacEngine(binary="tofu")
    paths: list[Path] = []

    async def boom(
        args: list[str], _cwd: Path, _env: Mapping[str, str] | None = None
    ) -> CommandResult:
        paths.append(Path(args[-1].removeprefix("-var-file=")))
        raise RuntimeError("engine crashed")

    with patch.object(IacEngine, "_run", side_effect=boom):
        with pytest.raises(RuntimeError):
            _ = asyncio.run(engine.plan(tmp_path, [], "p.plan", {}, {"a": 1}))
    assert paths and not paths[0].exists()


def test_import_places_the_vars_file_before_the_address_and_id(
    tmp_path: Path,
) -> None:
    engine = IacEngine(binary="tofu")
    seen: list[list[str]] = []

    async def fake_run(
        args: list[str], _cwd: Path, _env: Mapping[str, str] | None = None
    ) -> CommandResult:
        seen.append(args)
        return OK

    with patch.object(IacEngine, "_run", side_effect=fake_run):
        _ = asyncio.run(engine.import_resource(tmp_path, "a.b", "id-1", {}, {"x": 1}))
    args = seen[0]
    assert args[:3] == ["import", "-no-color", "-input=false"]
    assert args[3].startswith("-var-file=")
    assert args[4:] == ["a.b", "id-1"]


def test_no_vars_file_without_vars(tmp_path: Path) -> None:
    engine = IacEngine(binary="tofu")
    with patch.object(
        IacEngine, "_run", new_callable=AsyncMock, return_value=OK
    ) as run:
        _ = asyncio.run(engine.plan(tmp_path, [], "p.plan", ENV, {}))
    run.assert_awaited_once_with(
        ["plan", "-no-color", "-input=false", "-out", "p.plan"], tmp_path, ENV
    )
