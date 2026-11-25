# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""MAPPING_PREFIX_IDENTIFIER validation and normalization."""

from __future__ import annotations

import pytest

from src.config import Config, ConfigError


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("", ""),
        ("   ", ""),
        ("https://github.com/MySuperOrg/", "https://github.com/MySuperOrg/"),
        ("https://github.com/MySuperOrg", "https://github.com/MySuperOrg/"),
        (" https://git.example.com/group/sub ", "https://git.example.com/group/sub/"),
        (
            "https://org@dev.azure.com/org/p/_git/",
            "https://org@dev.azure.com/org/p/_git/",
        ),
    ],
)
def test_prefix_is_normalized(raw: str, expected: str) -> None:
    assert (
        Config(expected_token="", prefix_identifier=raw).prefix_identifier == expected
    )


@pytest.mark.parametrize(
    "raw",
    [
        "http://github.com/MySuperOrg/",
        "github.com/MySuperOrg/",
        "https:///no-host/",
        "https://user:secret@github.com/MySuperOrg/",
        "https://github.com/MySuperOrg/?ref=x",
        "https://github.com/MySuperOrg/#frag",
        "https://github.com/MySuperOrg/?",
        "https://github.com/MySuperOrg/#",
    ],
)
def test_bad_prefix_refuses_to_start(raw: str) -> None:
    with pytest.raises(ConfigError):
        _ = Config(expected_token="", prefix_identifier=raw)


def test_from_env_reads_the_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAPPING_PREFIX_IDENTIFIER", "https://github.com/MySuperOrg")
    monkeypatch.setenv("KUMOSS_MAPPING_TOKEN", "t")
    config = Config.from_env()
    assert config.prefix_identifier == "https://github.com/MySuperOrg/"
    assert config.expected_token == "t"


def test_bad_log_level_refuses_to_start() -> None:
    with pytest.raises(ConfigError):
        _ = Config(expected_token="", log_level="LOUD")
