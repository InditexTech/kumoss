"""Bearer-token authentication for the mapping service."""

from __future__ import annotations

from fastapi import HTTPException, status

from .config import Config


def verify_bearer_token(config: Config, authorization: str | None) -> None:
    """Raise HTTPException unless the request carries the expected token.

    If the service has no token configured, all requests are accepted.
    """
    if not config.expected_token:
        return

    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header.",
        )

    scheme, _, value = authorization.partition(" ")
    if scheme.lower() != "bearer" or value != config.expected_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid bearer token.",
        )
