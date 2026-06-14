# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from enum import Enum


class HealthStatus(str, Enum):
    OK = "ok"

    def __str__(self) -> str:
        return str(self.value)
