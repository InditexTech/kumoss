# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Bearer-token authentication for the notifications service."""

from __future__ import annotations

import hmac

from fastapi import HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import Config


bearer_scheme = HTTPBearer(scheme_name="bearerAuth", auto_error=False)


def verify_bearer_token(
    config: Config, credentials: HTTPAuthorizationCredentials | None
) -> None:
    """Raise HTTPException unless the request carries the expected token.

    If the service has no token configured, all requests are accepted;
    ``auto_error=False`` on the scheme is what keeps that decision here
    rather than in FastAPI, whose own error would be a 403 and would
    fire even with no token configured.

    The token comparison is constant-time (``hmac.compare_digest``) so an
    attacker on the service network cannot recover the token byte by byte
    from response timing.
    """
    if not config.expected_token:
        return

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed bearer credentials.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not hmac.compare_digest(
        credentials.credentials.encode("utf-8"),
        config.expected_token.encode("utf-8"),
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
