# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""OidcTokenValidator tests against a locally-generated RSA keypair.

The JWKS client is stubbed out (no network): only signature/claim
validation semantics are under test here.
"""

import json
import time
import unittest
from unittest.mock import MagicMock

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from src.infrastructure.auth.oidc import OidcTokenValidator
from src.infrastructure.exceptions import TokenValidationError

_ISSUER = "https://idp.test"
_CLIENT_ID = "nebula-web"
_KID = "test-kid"


def _pem(key: rsa.RSAPrivateKey) -> bytes:
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


class TestOidcTokenValidator(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.pem = _pem(cls.key)
        cls.other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(cls.key.public_key()))
        jwk.update({"kid": _KID, "alg": "RS256", "use": "sig"})
        cls.signing_key = jwt.PyJWK.from_dict(jwk)

    def _validator(self, audience: str = "", leeway: int = 60) -> OidcTokenValidator:
        validator = OidcTokenValidator(
            issuer_url=_ISSUER,
            client_id=_CLIENT_ID,
            audience=audience,
            leeway=leeway,
        )
        jwks = MagicMock()
        jwks.get_signing_key_from_jwt.return_value = self.signing_key
        validator._jwks = lambda: jwks
        return validator

    def _token(self, pem: bytes | None = None, **overrides) -> str:
        payload = {
            "iss": _ISSUER,
            "sub": "user-1",
            "aud": _CLIENT_ID,
            "exp": int(time.time()) + 300,
            "email": "alice@example.com",
            "name": "Alice",
        }
        payload.update(overrides)
        payload = {k: v for k, v in payload.items() if v is not None}
        return jwt.encode(
            payload, pem or self.pem, algorithm="RS256", headers={"kid": _KID}
        )

    async def test_valid_token_maps_claims(self):
        claims = await self._validator().validate(self._token())
        self.assertEqual(claims.issuer, _ISSUER)
        self.assertEqual(claims.subject, "user-1")
        self.assertEqual(claims.email, "alice@example.com")
        self.assertEqual(claims.name, "Alice")

    async def test_email_falls_back_to_preferred_username(self):
        token = self._token(email=None, preferred_username="alice@corp.example")
        claims = await self._validator().validate(token)
        self.assertEqual(claims.email, "alice@corp.example")

    async def test_wrong_signature_is_rejected(self):
        token = self._token(pem=_pem(self.other_key))
        with self.assertRaises(TokenValidationError):
            await self._validator().validate(token)

    async def test_wrong_issuer_is_rejected(self):
        with self.assertRaises(TokenValidationError):
            await self._validator().validate(self._token(iss="https://evil.test"))

    async def test_trailing_slash_issuer_is_accepted(self):
        claims = await self._validator().validate(self._token(iss=f"{_ISSUER}/"))
        self.assertEqual(claims.issuer, f"{_ISSUER}/")

    async def test_wrong_audience_is_rejected(self):
        with self.assertRaises(TokenValidationError):
            await self._validator().validate(self._token(aud="someone-else"))

    async def test_api_uri_audience_accepted_by_default(self):
        claims = await self._validator().validate(
            self._token(aud=f"api://{_CLIENT_ID}")
        )
        self.assertEqual(claims.subject, "user-1")

    async def test_configured_audience_overrides_client_id(self):
        validator = self._validator(audience="api://nebula")
        claims = await validator.validate(self._token(aud="api://nebula"))
        self.assertEqual(claims.subject, "user-1")
        with self.assertRaises(TokenValidationError):
            await validator.validate(self._token(aud=_CLIENT_ID))
        with self.assertRaises(TokenValidationError):
            await validator.validate(self._token(aud=f"api://{_CLIENT_ID}"))

    async def test_expired_token_is_rejected(self):
        token = self._token(exp=int(time.time()) - 300)
        with self.assertRaises(TokenValidationError):
            await self._validator().validate(token)

    async def test_expiry_inside_leeway_is_accepted(self):
        token = self._token(exp=int(time.time()) - 30)
        claims = await self._validator(leeway=60).validate(token)
        self.assertEqual(claims.subject, "user-1")

    async def test_missing_subject_is_rejected(self):
        with self.assertRaises(TokenValidationError):
            await self._validator().validate(self._token(sub=None))

    async def test_garbage_token_is_rejected(self):
        with self.assertRaises(TokenValidationError):
            await self._validator().validate("not-a-jwt")
