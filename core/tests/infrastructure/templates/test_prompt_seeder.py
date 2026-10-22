# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

# pyright: basic
import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from phoenix.client.types.prompts import PromptVersion

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


def test_new_prompt_is_tagged_with_every_environment(tmp_path: Path):
    seeder, prompts = _seeder(tmp_path)

    asyncio.run(seeder.ensure_seeded())

    tagged = [c.kwargs["name"] for c in prompts.tags.create.await_args_list]
    assert tagged == ["development", "staging", "production", "seed"]
    assert all(
        c.kwargs["prompt_version_id"] == "v1"
        for c in prompts.tags.create.await_args_list
    )


def test_tag_failure_names_the_tags_left_to_apply(tmp_path: Path):
    seeder, prompts = _seeder(tmp_path)
    prompts.tags.create.side_effect = [None, httpx.ReadTimeout("boom")]

    with pytest.raises(PromptSeedPushError) as exc:
        asyncio.run(seeder.ensure_seeded())

    assert "tag that version by hand with: staging, production, seed" in str(
        exc.value.message
    )


BODY = "anything"


def _version(text: str, version_id: str) -> PromptVersion:
    """A version as the Phoenix client hydrates a GET response, so a change
    in how the client stores it breaks these tests rather than the seeder."""
    return PromptVersion._loads(  # pyright: ignore[reportPrivateUsage]
        {
            "id": version_id,
            "model_provider": "OPENAI",
            "model_name": "kumoss-seed",
            "template": {
                "type": "chat",
                "messages": [
                    {"role": "user", "content": [{"type": "text", "text": text}]}
                ],
            },
            "template_type": "CHAT",
            "template_format": "NONE",
            "invocation_parameters": {"type": "openai", "openai": {}},
        }
    )


def _existing(
    tmp_path: Path,
    tagged: dict[str, PromptVersion],
    latest: PromptVersion | None = None,
) -> tuple[PromptSeeder, SimpleNamespace]:
    """A seeder whose prompt already exists, with ``tagged`` the version each
    tag points at (a tag missing from it is absent) and ``latest`` the newest
    version, the `seed` one by default."""
    seeder, prompts = _seeder(tmp_path)
    newest = latest or tagged["seed"]

    async def get(*, prompt_identifier: str, tag: str | None = None):
        if prompt_identifier == "kumoss_seed_probe_does_not_exist":
            raise ValueError("Prompt not found")
        if tag is None:
            return newest
        if tag not in tagged:
            raise ValueError("Prompt not found")
        return tagged[tag]

    prompts.get = AsyncMock(side_effect=get)
    return seeder, prompts


def _moved(prompts: SimpleNamespace) -> list[tuple[str, str]]:
    return [
        (c.kwargs["name"], c.kwargs["prompt_version_id"])
        for c in prompts.tags.create.await_args_list
    ]


def test_a_stale_seed_moves_every_tag_on_it_then_seed(tmp_path: Path):
    old = _version("old body", "v0")
    seeder, prompts = _existing(
        tmp_path,
        {"development": old, "staging": old, "production": old, "seed": old},
    )

    asyncio.run(seeder.ensure_seeded())

    prompts.create.assert_awaited_once()
    assert _moved(prompts) == [
        ("development", "v1"),
        ("staging", "v1"),
        ("production", "v1"),
        ("seed", "v1"),
    ]


def test_a_tag_on_another_version_is_never_moved(tmp_path: Path):
    # production points at a version an operator saved; staging was removed.
    old = _version("old body", "v0")
    seeder, prompts = _existing(
        tmp_path,
        {
            "development": old,
            "production": _version("my own prompt", "v5"),
            "seed": old,
        },
        latest=_version("my own prompt", "v5"),
    )

    asyncio.run(seeder.ensure_seeded())

    assert _moved(prompts) == [("development", "v1"), ("seed", "v1")]


def test_an_up_to_date_seed_is_left_alone(tmp_path: Path):
    current = _version(BODY, "v0")
    seeder, prompts = _existing(
        tmp_path,
        {"development": current, "production": _version("mine", "v5"), "seed": current},
    )

    asyncio.run(seeder.ensure_seeded())

    prompts.create.assert_not_awaited()
    prompts.tags.create.assert_not_awaited()


def test_without_a_seed_tag_the_latest_version_gets_it(tmp_path: Path):
    current = _version(BODY, "v3")
    seeder, prompts = _existing(
        tmp_path, {"development": current, "production": current}, latest=current
    )

    asyncio.run(seeder.ensure_seeded())

    prompts.create.assert_not_awaited()
    assert _moved(prompts) == [("seed", "v3")]


def test_a_stale_latest_version_without_a_seed_tag_is_updated(tmp_path: Path):
    # An install seeded before the tag existed, on a seed changed since.
    old = _version("old body", "v3")
    seeder, prompts = _existing(
        tmp_path, {"development": old, "production": old}, latest=old
    )

    asyncio.run(seeder.ensure_seeded())

    prompts.create.assert_awaited_once()
    assert _moved(prompts) == [
        ("seed", "v3"),
        ("development", "v1"),
        ("production", "v1"),
        ("seed", "v1"),
    ]


def test_stale_tags_join_a_current_version_instead_of_a_copy(tmp_path: Path):
    # An earlier boot pushed v2 and moved development, then failed.
    old = _version("old body", "v0")
    current = _version(BODY, "v2")
    seeder, prompts = _existing(
        tmp_path,
        {"development": current, "staging": old, "production": old, "seed": old},
        latest=current,
    )

    asyncio.run(seeder.ensure_seeded())

    prompts.create.assert_not_awaited()
    assert _moved(prompts) == [
        ("staging", "v2"),
        ("production", "v2"),
        ("seed", "v2"),
    ]


def test_the_seeder_recognizes_the_versions_it_writes(tmp_path: Path):
    # Round trip through the client's own serialization: what the seeder
    # pushes, read back as Phoenix returns it, is current.
    seeder, prompts = _seeder(tmp_path)
    asyncio.run(seeder.ensure_seeded())
    pushed: PromptVersion = prompts.create.await_args.kwargs["version"]
    stored = PromptVersion._loads(  # pyright: ignore[reportPrivateUsage]
        {**pushed._dumps(), "id": "v1"}  # pyright: ignore[reportPrivateUsage]
    )

    seeder, prompts = _existing(tmp_path / "again", {"seed": stored})
    asyncio.run(seeder.ensure_seeded())

    prompts.create.assert_not_awaited()
    prompts.tags.create.assert_not_awaited()


def test_a_seed_of_another_shape_is_stale(tmp_path: Path):
    # Only the one text message the seeder writes can match a seed.
    two_messages = PromptVersion._loads(  # pyright: ignore[reportPrivateUsage]
        {
            **_version(BODY, "v0")._dumps(),  # pyright: ignore[reportPrivateUsage]
            "id": "v0",
            "template": {
                "type": "chat",
                "messages": [
                    {"role": "user", "content": [{"type": "text", "text": BODY}]},
                    {"role": "user", "content": [{"type": "text", "text": "more"}]},
                ],
            },
        }
    )
    seeder, prompts = _existing(
        tmp_path, {"production": two_messages, "seed": two_messages}
    )

    asyncio.run(seeder.ensure_seeded())

    prompts.create.assert_awaited_once()
    assert _moved(prompts) == [("production", "v1"), ("seed", "v1")]
