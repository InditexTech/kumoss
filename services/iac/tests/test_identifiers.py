# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Deduplication of the resource identifier lists the endpoints answer with."""

from __future__ import annotations

from collections.abc import Iterator

from src.identifiers import unique


def test_unique_keeps_the_first_occurrence() -> None:
    assert unique(["b", "a", "b", "c", "a"]) == ["b", "a", "c"]


def test_unique_accepts_any_iterable() -> None:
    """`StateResourceIds` hands it a generator rather than a list."""

    def generated() -> Iterator[str]:
        yield from ["b", "a", "b"]

    assert unique(generated()) == ["b", "a"]


def test_unique_of_nothing_is_an_empty_list() -> None:
    assert unique([]) == []
