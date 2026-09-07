# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from dataclasses import dataclass


@dataclass(frozen=True)
class TokenClaims:
    """Value object: identity claims extracted from a validated token."""

    issuer: str
    subject: str
    email: str | None
    name: str | None
