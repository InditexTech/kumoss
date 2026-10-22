# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from dataclasses import dataclass

from src.domains.value_objects.search_result import SearchResult


@dataclass(frozen=True)
class PageSummary:
    """Value object: one page's condensed content plus its position in the engine order."""

    index: int  # 0-based, as the ids the selection inference returns
    result: SearchResult
    summary: str
