# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Argument assembly of the engine commands the import endpoints run."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

from src.engine import CommandResult, IacEngine


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


def test_state_pull_runs_on_the_unmodified_environment() -> None:
    engine = IacEngine(binary="tofu")
    ok = CommandResult(ok=True, stdout="{}", stderr="")
    with patch.object(
        IacEngine, "_run", new_callable=AsyncMock, return_value=ok
    ) as run:
        result = asyncio.run(engine.state_pull(Path("/ws")))
    assert result is ok
    run.assert_awaited_once_with(["state", "pull"], Path("/ws"))
