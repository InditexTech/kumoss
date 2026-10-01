# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

# pyright: basic
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from src.infrastructure.exceptions import PromptSeedPushError
from src.infrastructure.templates.prompt_seeder import PromptSeeder


def _seeder(tmp_path: Path) -> tuple[PromptSeeder, SimpleNamespace]:
    seed = tmp_path / "general" / "guidelines" / "terraform.yaml"
    seed.parent.mkdir(parents=True)
    seed.write_text("body: anything\n", encoding="utf-8")

    seeder = PromptSeeder(tmp_path, "http://phoenix.invalid")
    prompts = SimpleNamespace(
        # 404 for the probe and the existence check: the prompt is missing.
        get=AsyncMock(side_effect=ValueError("Prompt not found")),
        create=AsyncMock(return_value=SimpleNamespace(id="v1")),
        tags=SimpleNamespace(create=AsyncMock()),
    )
    seeder._client = SimpleNamespace(prompts=prompts)  # type: ignore[assignment]
    return seeder, prompts


async def test_new_prompt_is_tagged_with_every_environment(tmp_path: Path):
    seeder, prompts = _seeder(tmp_path)

    await seeder.ensure_seeded()

    tagged = [c.kwargs["name"] for c in prompts.tags.create.await_args_list]
    assert tagged == ["development", "staging", "production"]
    assert all(
        c.kwargs["prompt_version_id"] == "v1"
        for c in prompts.tags.create.await_args_list
    )


async def test_tag_failure_names_the_tags_left_to_apply(tmp_path: Path):
    seeder, prompts = _seeder(tmp_path)
    prompts.tags.create.side_effect = [None, httpx.ReadTimeout("boom")]

    with pytest.raises(PromptSeedPushError) as exc:
        await seeder.ensure_seeded()

    assert "tag that version by hand with: staging, production" in str(
        exc.value.message
    )
