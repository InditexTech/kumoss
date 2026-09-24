# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from enum import Enum, unique


@unique
class OperationKind(Enum):
    DRIFT = "DRIFT"
    IMPORT = "IMPORT"
    # por ahora estos ns si vamos a querer meter más

@unique
class OperationStatus(Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
