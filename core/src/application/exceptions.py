# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0


from src.shared.exceptions import ExceptionHandler


class SessionConflict(ExceptionHandler):
    """Another call on this session is already in-flight (HTTP 409)."""

    pass


class SessionForbidden(ExceptionHandler):
    """Session belongs to a different user_id (HTTP 403)."""

    pass


class SessionTerminal(ExceptionHandler):
    """Session is completed or abandoned (HTTP 409 with current status)."""

    pass


class MissingArgumentError(ExceptionHandler):
    pass
