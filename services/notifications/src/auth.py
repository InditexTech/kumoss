# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Bearer-token authentication for the notifications service."""

from __future__ import annotations

import hmac
import logging

from fastapi import HTTPException, status

from .config import Config

logger = logging.getLogger("nebula.notifications.auth")


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

    Rejections are logged (without the presented or expected token) so a
    core↔sidecar token mismatch is visible in the sidecar's own log.
    """
    if not config.expected_token:
        return

    if not authorization:
        logger.warning("rejected request: missing Authorization header")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header.",
        )

    scheme, _, value = authorization.partition(" ")
    if scheme.lower() != "bearer":
        logger.warning("rejected request: Authorization scheme is not Bearer")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid bearer token.",
        )
    if not hmac.compare_digest(
        value.encode("utf-8"), config.expected_token.encode("utf-8")
    ):
        logger.warning(
            "rejected request: bearer token does not match "
            "NEBULA_NOTIFICATIONS_TOKEN (check core/.env vs services/notifications/.env)"
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid bearer token.",
        )
