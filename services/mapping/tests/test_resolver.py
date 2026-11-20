# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Identifier to clone URL: passthrough and prefix resolution."""

from __future__ import annotations

import pytest

from src.resolver import NotResolvable, resolve

PREFIX = "https://github.com/MySuperOrg/"


@pytest.mark.parametrize(
    ("identifier", "expected"),
    [
        ("foo", "https://github.com/MySuperOrg/foo.git"),
        ("foo.git", "https://github.com/MySuperOrg/foo.git"),
        ("my-iac_repo.v2", "https://github.com/MySuperOrg/my-iac_repo.v2.git"),
        (".github", "https://github.com/MySuperOrg/.github.git"),
        ("  foo  ", "https://github.com/MySuperOrg/foo.git"),
    ],
)
def test_bare_name_is_appended_to_the_prefix(identifier: str, expected: str) -> None:
    assert resolve(identifier, PREFIX) == expected


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/other/repo.git",
        "HTTPS://dev.azure.com/org/project/_git/repo",
        "https://org@dev.azure.com/org/project/_git/repo",
    ],
)
def test_https_url_passes_through_unchanged(url: str) -> None:
    assert resolve(url, PREFIX) == url
    assert resolve(url, "") == url


@pytest.mark.parametrize(
    "identifier",
    [
        "team/foo",
        "../foo",
        "foo?x=1",
        "http://github.com/me/repo.git",
        "git@github.com:me/repo.git",
        "file:///srv/repo.git",
        ".",
        "..",
        ".git",
        "foo bar",
        "",
    ],
)
def test_anything_else_is_not_resolvable(identifier: str) -> None:
    with pytest.raises(NotResolvable):
        _ = resolve(identifier, PREFIX)


def test_bare_name_without_prefix_names_the_setting() -> None:
    with pytest.raises(NotResolvable, match="MAPPING_PREFIX_IDENTIFIER"):
        _ = resolve("foo", "")
