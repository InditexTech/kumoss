# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

# pyright: basic
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from src.infrastructure.exceptions import PromptSeedPushError
from src.infrastructure.templates.prompt_seeder import PromptSeeder
from tests.infrastructure.templates.fake_langfuse import FakeLangfuse

NAME = "general/guidelines/terraform"
BODY = "anything"
ENVS = ("development", "staging", "production")


def _seed(tmp_path: Path, langfuse: FakeLangfuse) -> None:
    seed = tmp_path / "general" / "guidelines" / "terraform.yaml"
    seed.parent.mkdir(parents=True, exist_ok=True)
    seed.write_text(f"body: {BODY}\ndescription: the seed\n", encoding="utf-8")
    asyncio.run(PromptSeeder(tmp_path, langfuse.client()).ensure_seeded())


def test_a_new_prompt_gets_every_environment_label_and_seed(tmp_path: Path):
    langfuse = FakeLangfuse()

    _seed(tmp_path, langfuse)

    # Created with its labels in one request: no window without them.
    assert langfuse.writes == [("create", NAME, (*ENVS, "seed"))]
    assert langfuse.labels(NAME) == {
        "development": 1,
        "staging": 1,
        "production": 1,
        "seed": 1,
        "latest": 1,
    }
    assert langfuse.prompts[NAME][0].body == BODY


def test_a_stale_seed_moves_every_label_on_it(tmp_path: Path):
    langfuse = FakeLangfuse()
    langfuse.add(NAME, "old body", (*ENVS, "seed"))

    _seed(tmp_path, langfuse)

    assert langfuse.writes == [("create", NAME, (*ENVS, "seed"))]
    assert langfuse.labels(NAME) == {
        "development": 2,
        "staging": 2,
        "production": 2,
        "seed": 2,
        "latest": 2,
    }


def test_a_label_on_another_version_is_never_moved(tmp_path: Path):
    # production points at a version an operator saved; staging was removed.
    langfuse = FakeLangfuse()
    langfuse.add(NAME, "old body", ("development", "seed"))
    langfuse.add(NAME, "my own prompt", ("production",))

    _seed(tmp_path, langfuse)

    assert langfuse.labels(NAME) == {
        "development": 3,
        "seed": 3,
        "production": 2,
        "latest": 3,
    }


def test_an_up_to_date_seed_is_left_alone(tmp_path: Path):
    langfuse = FakeLangfuse()
    langfuse.add(NAME, BODY, ("development", "seed"))
    langfuse.add(NAME, "mine", ("production",))

    _seed(tmp_path, langfuse)

    assert langfuse.writes == []


def test_without_a_seed_label_the_latest_version_gets_it(tmp_path: Path):
    langfuse = FakeLangfuse()
    langfuse.add(NAME, BODY, ("development", "production"))

    _seed(tmp_path, langfuse)

    assert langfuse.writes == [("label", NAME, (1, ("seed",)))]


def test_a_stale_latest_version_without_a_seed_label_is_updated(tmp_path: Path):
    # A prompt store migrated without the label, on a seed changed since.
    langfuse = FakeLangfuse()
    langfuse.add(NAME, "old body", ("development", "production"))

    _seed(tmp_path, langfuse)

    assert langfuse.writes == [
        ("label", NAME, (1, ("seed",))),
        ("create", NAME, ("development", "production", "seed")),
    ]
    assert langfuse.labels(NAME) == {
        "development": 2,
        "production": 2,
        "seed": 2,
        "latest": 2,
    }


def test_stale_labels_join_a_current_version_instead_of_a_copy(tmp_path: Path):
    # The new seed text was saved by hand before this boot.
    langfuse = FakeLangfuse()
    langfuse.add(NAME, "old body", (*ENVS, "seed"))
    langfuse.add(NAME, BODY)

    _seed(tmp_path, langfuse)

    assert langfuse.writes == [("label", NAME, (2, (*ENVS, "seed")))]


def test_the_seeder_recognizes_the_versions_it_writes(tmp_path: Path):
    langfuse = FakeLangfuse()
    _seed(tmp_path, langfuse)
    writes = list(langfuse.writes)

    _seed(tmp_path, langfuse)

    assert langfuse.writes == writes


def test_a_seed_of_another_shape_is_stale(tmp_path: Path):
    # Only a single text matches a seed: a chat prompt of two messages does not.
    langfuse = FakeLangfuse()
    two_messages = [
        {"role": "user", "content": BODY},
        {"role": "user", "content": "more"},
    ]
    langfuse.add(NAME, two_messages, ("production", "seed"), type="chat")

    _seed(tmp_path, langfuse)

    assert langfuse.writes == [("create", NAME, ("production", "seed"))]
    # Still a chat prompt: Langfuse refuses a version of another type.
    pushed = langfuse.prompts[NAME][-1]
    assert (pushed.type, pushed.body) == ("chat", [{"role": "user", "content": BODY}])


def test_a_stale_chat_seed_is_updated_as_a_chat_prompt(tmp_path: Path):
    # An operator saved the prompt as chat in the Langfuse UI.
    langfuse = FakeLangfuse()
    old = [{"role": "system", "content": "old body"}]
    langfuse.add(NAME, old, (*ENVS, "seed"), type="chat")

    _seed(tmp_path, langfuse)

    assert langfuse.writes == [("create", NAME, (*ENVS, "seed"))]
    pushed = langfuse.prompts[NAME][-1]
    assert (pushed.type, pushed.body) == (
        "chat",
        [{"role": "system", "content": BODY}],
    )


def test_a_refused_key_pair_fails_at_once_and_says_so(tmp_path: Path):
    langfuse = FakeLangfuse()
    langfuse.fail = lambda _: httpx.Response(401, json={"message": "Unauthorized"})

    with patch("asyncio.sleep", AsyncMock()) as sleep:
        with pytest.raises(PromptSeedPushError) as exc:
            _seed(tmp_path, langfuse)

    sleep.assert_not_awaited()
    assert "refused the API key pair (401)" in exc.value.message


def test_a_booting_langfuse_is_waited_for(tmp_path: Path):
    langfuse = FakeLangfuse()
    answers = iter([httpx.ConnectError("refused"), httpx.Response(503)])

    def booting(request: httpx.Request) -> httpx.Response | None:
        answer = next(answers, None)
        if isinstance(answer, Exception):
            raise answer
        return answer

    langfuse.fail = booting

    with patch("asyncio.sleep", AsyncMock()) as sleep:
        _seed(tmp_path, langfuse)

    assert sleep.await_count == 2
    assert langfuse.writes == [("create", NAME, (*ENVS, "seed"))]


def test_a_failed_label_move_names_the_version_and_labels(tmp_path: Path):
    langfuse = FakeLangfuse()
    langfuse.add(NAME, "old body", (*ENVS, "seed"))
    langfuse.add(NAME, BODY)
    langfuse.fail = lambda r: httpx.Response(500) if r.method == "PATCH" else None

    with pytest.raises(PromptSeedPushError) as exc:
        _seed(tmp_path, langfuse)

    assert (
        f"Failed to label '{NAME}' version 2 with development, staging, "
        + "production, seed"
    ) in exc.value.message
