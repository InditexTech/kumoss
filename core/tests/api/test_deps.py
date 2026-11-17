# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from src.api.deps import get_validated_claims
from src.domains.value_objects.token_claims import DEV_CLAIMS


class TestGetValidatedClaims(unittest.IsolatedAsyncioTestCase):
    @patch("src.api.deps._oidc_enabled", return_value=False)
    async def test_disabled_oidc_returns_dev_claims(self, _mock):
        result = await get_validated_claims(credentials=None)
        self.assertIs(result, DEV_CLAIMS)

    @patch("src.api.deps._oidc_enabled", return_value=True)
    async def test_missing_credentials_raises_401(self, _mock):
        with self.assertRaises(HTTPException) as ctx:
            await get_validated_claims(credentials=None)
        self.assertEqual(ctx.exception.status_code, 401)

    @patch("src.api.deps._oidc_enabled", return_value=True)
    @patch("src.api.deps.oidc")
    async def test_valid_credentials_returns_claims(self, mock_oidc, _mock):
        from src.domains.value_objects.token_claims import TokenClaims

        expected = TokenClaims(
            issuer="https://idp.test",
            subject="u1",
            email="a@b.com",
            name="A",
            email_verified=True,
        )
        mock_oidc.oidc_validator = AsyncMock()
        mock_oidc.oidc_validator.validate = AsyncMock(return_value=expected)

        creds = type("C", (), {"credentials": "tok"})()
        result = await get_validated_claims(credentials=creds)
        self.assertEqual(result, expected)
