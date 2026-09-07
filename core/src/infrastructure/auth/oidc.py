# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""OIDC bearer-token validation against the configured issuer."""

import threading

import httpx
import jwt

from src.domains.value_objects import TokenClaims
from src.infrastructure.exceptions import TokenValidationError
from src.shared.config.system_config import system_config
from src.shared.utils.decorators import execute_pool

_ALGORITHMS = [
    "RS256",
    "RS384",
    "RS512",
    "ES256",
    "ES384",
    "ES512",
    "PS256",
    "PS384",
    "PS512",
]
_DISCOVERY_TIMEOUT = 10.0


class OidcTokenValidator:
    """Validates bearer JWTs via the issuer's discovery document and JWKS.

    The blocking discovery fetch and ``PyJWKClient`` run on the shared
    thread pool. Discovery is resolved lazily on first validation so boot
    never depends on the IdP being reachable; ``PyJWKClient`` caches the
    JWK set and refreshes it on expiry, which also covers key rotation.
    """

    def __init__(self, issuer_url: str, client_id: str, audience: str, leeway: int):
        self._issuer: str = issuer_url.rstrip("/")
        self._audiences: list[str] = (
            [audience] if audience else [client_id, f"api://{client_id}"]
        )
        self._leeway: int = leeway
        self._jwks_client: jwt.PyJWKClient | None = None
        self._jwks_lock: threading.Lock = threading.Lock()

    def _jwks(self) -> jwt.PyJWKClient:
        with self._jwks_lock:
            if self._jwks_client is None:
                response = httpx.get(
                    f"{self._issuer}/.well-known/openid-configuration",
                    timeout=_DISCOVERY_TIMEOUT,
                )
                _ = response.raise_for_status()
                self._jwks_client = jwt.PyJWKClient(
                    response.json()["jwks_uri"], cache_keys=True
                )
            return self._jwks_client

    @execute_pool
    def _validate(self, token: str) -> TokenClaims:
        signing_key = self._jwks().get_signing_key_from_jwt(token)
        payload = jwt.decode(
            token,
            key=signing_key.key,
            algorithms=_ALGORITHMS,
            audience=self._audiences,
            # Some IdPs (e.g. Auth0) emit `iss` with a trailing slash.
            issuer=[self._issuer, f"{self._issuer}/"],
            leeway=self._leeway,
            options={"require": ["exp", "iss", "sub"]},
        )
        return TokenClaims(
            issuer=payload["iss"],
            subject=payload["sub"],
            email=payload.get("email") or payload.get("preferred_username"),
            name=payload.get("name"),
        )

    async def validate(self, token: str) -> TokenClaims:
        try:
            return await self._validate(token)
        except TokenValidationError:
            raise
        except Exception as e:
            raise TokenValidationError(f"Token validation failed: {e}")


def _build_validator() -> OidcTokenValidator | None:
    cfg = system_config.oidc
    if not cfg.issuer_url:
        return None
    return OidcTokenValidator(
        issuer_url=cfg.issuer_url,
        client_id=cfg.client_id,
        audience=cfg.audience,
        leeway=cfg.clock_skew_seconds,
    )


oidc_validator: OidcTokenValidator | None = _build_validator()
