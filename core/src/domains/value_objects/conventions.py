# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from dataclasses import dataclass


@dataclass(frozen=True)
class Conventions:
    """Value object: best practices and conventions captured at PROMPT_COMPOSITOR generation.

    ``templates`` list of template names.
    ``abbreviations`` list of terraform resource name conventions.
    """

    templates: list[str]
    abbreviations: list[str]

    @classmethod
    def empty(cls) -> "Conventions":
        return cls(templates=[], abbreviations=[])
