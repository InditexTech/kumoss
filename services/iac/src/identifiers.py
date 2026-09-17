# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Resource identifier sequences the import endpoints answer with."""

from __future__ import annotations

from collections.abc import Iterable


def unique(ids: Iterable[str]) -> list[str]:
    """The identifiers without repeats, in first-seen order."""
    seen: set[str] = set()
    ordered: list[str] = []
    for identifier in ids:
        if identifier not in seen:
            seen.add(identifier)
            ordered.append(identifier)
    return ordered
