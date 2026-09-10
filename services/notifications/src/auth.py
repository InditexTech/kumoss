# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Bearer-token authentication for the notifications service."""

from __future__ import annotations

import hmac

from fastapi import HTTPException, status

from .config import Config


def verify_bearer_token(
    config: Config,
    authorization: str | None,
) -> None:
    """Raise HTTPException unless the request carries the expected token.

    If the service has no token configured (``expected_token`` is empty), all
    requests are accepted. This is documented as local-dev-only behavior.

    The token comparison is constant-time (``hmac.compare_digest``) so an
    attacker on the service network cannot recover the token byte by byte
    from response timing (docs/specs/authentication.md, SVC-1).
    """
    if not config.expected_token:
        return

    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header.",
        )

    scheme, _, value = authorization.partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(
        value.encode("utf-8"), config.expected_token.encode("utf-8")
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid bearer token.",
        )
