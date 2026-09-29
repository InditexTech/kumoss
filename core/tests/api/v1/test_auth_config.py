# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Contract tests for the public GET /v1/auth/config endpoint."""

import unittest
from unittest.mock import patch

from httpx import ASGITransport, AsyncClient

from src.main import app
from src.shared.config.system_config import OidcConfig


class TestAuthConfig(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        )

    async def asyncTearDown(self):
        await self.client.aclose()

    async def test_returns_configured_values(self):
        oidc = OidcConfig(
            issuer_url="https://idp.example.com/realms/kumoss",
            client_id="kumoss-spa",
            audience="kumoss-api",
            scope="openid profile email custom",
        )
        with patch("src.api.v1.auth.system_config") as cfg:
            cfg.oidc = oidc
            resp = await self.client.get("/v1/auth/config")
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(
            resp.json(),
            {
                "issuer_url": "https://idp.example.com/realms/kumoss",
                "client_id": "kumoss-spa",
                "audience": "kumoss-api",
                "scope": "openid profile email custom",
            },
        )

    async def test_scope_placeholder_served_expanded(self):
        oidc = OidcConfig(
            issuer_url="https://idp.example.com/realms/kumoss",
            client_id="kumoss-spa",
            scope="openid api://{client_id}/access_as_user",
        )
        with patch("src.api.v1.auth.system_config") as cfg:
            cfg.oidc = oidc
            resp = await self.client.get("/v1/auth/config")
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["scope"], "openid api://kumoss-spa/access_as_user")
        self.assertEqual(body["audience"], "")

    async def test_blank_issuer_means_auth_disabled(self):
        with patch("src.api.v1.auth.system_config") as cfg:
            cfg.oidc = OidcConfig()
            resp = await self.client.get("/v1/auth/config")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["issuer_url"], "")
        self.assertEqual(body["scope"], "openid profile email")

    async def test_open_without_token_when_auth_enabled(self):
        with patch("src.api.deps._oidc_enabled", return_value=True):
            resp = await self.client.get("/v1/auth/config")
        self.assertEqual(resp.status_code, 200, resp.text)
