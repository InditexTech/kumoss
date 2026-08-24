# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from dataclasses import dataclass

from src.shared.constants import SessionStatus


@dataclass(frozen=True)
class Status:
    """Value object: a session status and its associated message."""

    status: SessionStatus
    msg: str
