# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from dataclasses import dataclass


@dataclass(frozen=True)
class TokenClaims:
    """Value object: identity claims extracted from a validated token.

    ``email_verified`` is True only when the token carried an ``email``
    claim together with ``email_verified: true``; a missing flag or a
    ``preferred_username`` fallback stored in ``email`` leaves it False.
    """

    issuer: str
    subject: str
    email: str | None
    name: str | None
    email_verified: bool = False
