# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from enum import Enum


class JobKind(str, Enum):
    APPLY = "apply"
    IMPORT = "import"
    VALIDATE = "validate"

    def __str__(self) -> str:
        return str(self.value)
