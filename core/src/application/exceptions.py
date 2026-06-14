# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0


class SessionConflict(Exception):
    """Another call on this session is already in-flight (HTTP 409)."""


class SessionForbidden(Exception):
    """Session belongs to a different user_id (HTTP 403)."""


class SessionTerminal(Exception):
    """Session is completed or abandoned (HTTP 409 with current status)."""
