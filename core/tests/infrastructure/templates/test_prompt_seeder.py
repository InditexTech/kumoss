# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

# pyright: basic
import hashlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

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


BODY = "anything"


def _version(
    text: str, description: str | None, version_id: str = "v0"
) -> PromptVersion:
    """A version as the Phoenix client hydrates a GET response, so a change
    in how the client stores it breaks these tests rather than the seeder."""
    data = {
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
    if description is not None:
        data["description"] = description
    return PromptVersion._loads(data)  # pyright: ignore[reportPrivateUsage]


def _marked(text: str) -> str:
    return f"Seed [kumoss-seed sha256:{hashlib.sha256(text.encode()).hexdigest()}]"


def _existing(
    tmp_path: Path, tagged: dict[str, SimpleNamespace]
) -> tuple[PromptSeeder, SimpleNamespace]:
    """A seeder whose prompt already exists, with ``tagged`` the version each
    environment tag points at; a tag missing from it was removed."""
    seeder, prompts = _seeder(tmp_path)

    async def get(*, prompt_identifier: str, tag: str | None = None):
        if prompt_identifier == "kumoss_seed_probe_does_not_exist":
            raise ValueError("Prompt not found")
        if tag is None:
            return next(iter(tagged.values()), _version(BODY, None))
        if tag not in tagged:
            raise ValueError("Prompt not found")
        return tagged[tag]

    prompts.get = AsyncMock(side_effect=get)
    return seeder, prompts


def _moved(prompts: SimpleNamespace) -> list[str]:
    return [c.kwargs["name"] for c in prompts.tags.create.await_args_list]


async def test_a_new_version_carries_the_digest_of_its_text(tmp_path: Path):
    seeder, prompts = _seeder(tmp_path)

    await seeder.ensure_seeded()

    version = prompts.create.await_args.kwargs["version"]
    assert _marked(BODY).removeprefix("Seed ") in version._description


async def test_a_stale_seeded_prompt_is_updated_under_every_tag(tmp_path: Path):
    old = _version("old body", _marked("old body"))
    seeder, prompts = _existing(
        tmp_path, {"development": old, "staging": old, "production": old}
    )

    await seeder.ensure_seeded()

    prompts.create.assert_awaited_once()
    assert _moved(prompts) == ["development", "staging", "production"]


async def test_a_released_version_without_a_marker_is_updated(tmp_path: Path):
    released = "released body"
    seeder, prompts = _existing(tmp_path, {"production": _version(released, None)})

    with patch(
        "src.infrastructure.templates.prompt_seeder.RELEASED_SEED_DIGESTS",
        frozenset({hashlib.sha256(released.encode()).hexdigest()}),
    ):
        await seeder.ensure_seeded()

    assert _moved(prompts) == ["production"]


async def test_a_curated_version_is_never_overwritten(tmp_path: Path):
    # Saved by a user: no marker and not a released seed, or a copied
    # marker that no longer matches the edited text.
    seeder, prompts = _existing(
        tmp_path,
        {
            "development": _version("my own prompt", None),
            "staging": _version("edited copy", _marked("old body")),
        },
    )

    await seeder.ensure_seeded()

    prompts.create.assert_not_awaited()
    prompts.tags.create.assert_not_awaited()


async def test_only_stale_tags_move(tmp_path: Path):
    # production is curated, staging already current, development stale;
    # no tag is ever created for an environment an operator untagged.
    seeder, prompts = _existing(
        tmp_path,
        {
            "development": _version("old body", _marked("old body")),
            "staging": _version(BODY, _marked(BODY), version_id="v2"),
            "production": _version("my own prompt", None),
        },
    )

    await seeder.ensure_seeded()

    assert _moved(prompts) == ["development"]


async def test_stale_tags_join_a_current_version_instead_of_a_copy(tmp_path: Path):
    # An earlier boot moved development, then failed tagging the rest.
    old = _version("old body", _marked("old body"))
    seeder, prompts = _existing(
        tmp_path,
        {
            "development": _version(BODY, _marked(BODY), version_id="v2"),
            "staging": old,
            "production": old,
        },
    )

    await seeder.ensure_seeded()

    prompts.create.assert_not_awaited()
    assert _moved(prompts) == ["staging", "production"]
    assert all(
        c.kwargs["prompt_version_id"] == "v2"
        for c in prompts.tags.create.await_args_list
    )


async def test_the_seeder_recognizes_the_versions_it_writes(tmp_path: Path):
    # Round trip through the client's own serialization: what the seeder
    # pushes, read back as Phoenix returns it, is current and seeder-pushed.
    seeder, prompts = _seeder(tmp_path)
    await seeder.ensure_seeded()
    pushed: PromptVersion = prompts.create.await_args.kwargs["version"]
    stored = PromptVersion._loads(  # pyright: ignore[reportPrivateUsage]
        {**pushed._dumps(), "id": "v1"}  # pyright: ignore[reportPrivateUsage]
    )

    seeder, prompts = _existing(
        tmp_path / "again",
        {"development": stored, "staging": stored, "production": stored},
    )
    await seeder.ensure_seeded()

    prompts.create.assert_not_awaited()
    prompts.tags.create.assert_not_awaited()


async def test_a_version_of_another_shape_is_curated(tmp_path: Path):
    # Only a user saves more than the one text message the seeder writes,
    # even when the first message is a released seed.
    old = "old body"
    two_messages = _version(old, _marked(old))
    two_messages = PromptVersion._loads(  # pyright: ignore[reportPrivateUsage]
        {
            **two_messages._dumps(),  # pyright: ignore[reportPrivateUsage]
            "id": "v3",
            "template": {
                "type": "chat",
                "messages": [
                    {"role": "user", "content": [{"type": "text", "text": old}]},
                    {"role": "user", "content": [{"type": "text", "text": "more"}]},
                ],
            },
        }
    )
    seeder, prompts = _existing(tmp_path, {"production": two_messages})

    await seeder.ensure_seeded()

    prompts.create.assert_not_awaited()
    prompts.tags.create.assert_not_awaited()


async def test_an_up_to_date_prompt_is_left_alone(tmp_path: Path):
    current = _version(BODY, _marked(BODY))
    seeder, prompts = _existing(
        tmp_path, {"development": current, "staging": current, "production": current}
    )

    await seeder.ensure_seeded()

    prompts.create.assert_not_awaited()
