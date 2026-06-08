"""Bearer-token authentication for the notifications service."""

from __future__ import annotations

from fastapi import Header, HTTPException, status

from .config import Config


def verify_bearer_token(
    config: Config,
    authorization: str | None,
) -> None:
    """Raise HTTPException unless the request carries the expected token.

    If the service has no token configured (``expected_token`` is empty), all
    requests are accepted. This is documented as local-dev-only behavior.
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


def authorization_header() -> str | None:
    """FastAPI dependency-friendly accessor for the Authorization header."""
    # Wrapper so callers can `Depends(authorization_header)` if they prefer
    # injection over reading the header inline. Currently the route reads it
    # via Header() directly; this keeps the import surface for tests stable.
    raise NotImplementedError  # not used at runtime; tests use Header() too
