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
from unittest.mock import MagicMock, patch

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from src.infrastructure.auth.oidc import OidcTokenValidator
from src.infrastructure.exceptions import TokenValidationError

_ISSUER = "https://idp.test"
_CLIENT_ID = "kumoss-web"
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
            "email_verified": True,
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
        self.assertTrue(claims.email_verified)

    async def test_missing_email_claim_yields_none(self):
        token = self._token(email=None, preferred_username="alice@corp.example")
        claims = await self._validator().validate(token)
        self.assertIsNone(claims.email)
        self.assertFalse(claims.email_verified)

    async def test_explicitly_unverified_email_is_flagged(self):
        claims = await self._validator().validate(self._token(email_verified=False))
        self.assertEqual(claims.email, "alice@example.com")
        self.assertFalse(claims.email_verified)

    async def test_missing_email_verified_claim_counts_as_unverified(self):
        claims = await self._validator().validate(self._token(email_verified=None))
        self.assertEqual(claims.email, "alice@example.com")
        self.assertFalse(claims.email_verified)

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
        validator = self._validator(audience="api://kumoss")
        claims = await validator.validate(self._token(aud="api://kumoss"))
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

    async def test_universal_claims_extracted_into_properties(self):
        claims = await self._validator().validate(self._token())
        self.assertEqual(claims.properties["issuer"], _ISSUER)
        self.assertEqual(claims.properties["email"], "alice@example.com")

    @patch("src.infrastructure.auth.oidc.system_config")
    async def test_extra_claims_merged_into_properties(self, mock_cfg):
        mock_cfg.oidc.claims = {"identifier": "oid", "tenant_id": "tid"}
        mock_cfg.oidc.issuer_url = _ISSUER
        mock_cfg.oidc.client_id = _CLIENT_ID
        mock_cfg.oidc.audience = ""
        mock_cfg.oidc.clock_skew_seconds = 60
        token = self._token(oid="obj-id-123", tid="tenant-abc")
        claims = await self._validator().validate(token)
        self.assertEqual(claims.properties["identifier"], "obj-id-123")
        self.assertEqual(claims.properties["tenant_id"], "tenant-abc")
        self.assertEqual(claims.properties["issuer"], _ISSUER)

    @patch("src.infrastructure.auth.oidc.system_config")
    async def test_extra_claims_override_universal_defaults(self, mock_cfg):
        mock_cfg.oidc.claims = {"email": "preferred_username"}
        token = self._token(email="formal@example.com", preferred_username="alice@corp")
        claims = await self._validator().validate(token)
        self.assertEqual(claims.properties["email"], "alice@corp")

    async def test_missing_claim_excluded_from_properties(self):
        claims = await self._validator().validate(self._token())
        self.assertNotIn("groups", claims.properties)

    @patch("src.infrastructure.auth.oidc.system_config")
    async def test_groups_in_properties_when_configured(self, mock_cfg):
        mock_cfg.oidc.claims = {"groups": "groups"}
        token = self._token(groups=["team-a", "team-b"])
        claims = await self._validator().validate(token)
        self.assertEqual(claims.properties["groups"], ["team-a", "team-b"])

    @patch("src.infrastructure.auth.oidc.system_config")
    async def test_groups_claim_populates_fixed_field(self, mock_cfg):
        mock_cfg.oidc.claims = {"groups": "groups"}
        token = self._token(groups=["team-a", "team-b"])
        claims = await self._validator().validate(token)
        self.assertEqual(claims.groups, ["team-a", "team-b"])

    async def test_missing_groups_claim_yields_empty_list(self):
        claims = await self._validator().validate(self._token())
        self.assertEqual(claims.groups, [])

    @patch("src.infrastructure.auth.oidc.system_config")
    async def test_non_list_groups_yields_empty_list(self, mock_cfg):
        mock_cfg.oidc.claims = {"groups": "groups"}
        token = self._token(groups="not-a-list")
        claims = await self._validator().validate(token)
        self.assertEqual(claims.groups, [])

    async def test_none_values_excluded_from_properties(self):
        token = self._token(email=None)
        claims = await self._validator().validate(token)
        self.assertNotIn("email", claims.properties)
