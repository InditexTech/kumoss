# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from dataclasses import dataclass


@dataclass(frozen=True)
class Lock:
    """Value object: a snapshot of a session's concurrency lock state.

    ``in_flight`` is True while an operation currently holds the session;
    ``is_blocked`` is True while the session is blocked from progressing.
    """

    in_flight: bool
    is_blocked: bool
