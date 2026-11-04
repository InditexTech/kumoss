# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from enum import StrEnum


class ResourceType(StrEnum):
    SCOPE = "scope"

    def __str__(self) -> str:
        return str(self.value)
