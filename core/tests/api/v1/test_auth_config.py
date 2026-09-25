# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Contract tests for the public GET /v1/auth/config endpoint."""

import unittest
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

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

    @contextmanager
    def _config(self, oidc: OidcConfig, prefix: str = "x-amz-meta-"):
        """Patch both sources the endpoint reads.

        The object storage factory is patched too, not just `system_config`:
        it is `@cache`-d, so a real call here would build (and pin) an
        adapter from whatever config the test environment happens to hold.
        """
        with (
            patch("src.api.v1.auth.system_config") as cfg,
            patch("src.api.v1.auth.default_object_storage") as storage,
        ):
            cfg.oidc = oidc
            storage.return_value = MagicMock(metadata_header_prefix=prefix)
            yield

    async def test_returns_configured_values(self):
        oidc = OidcConfig(
            issuer_url="https://idp.example.com/realms/nebula",
            client_id="nebula-spa",
            audience="nebula-api",
            scope="openid profile email custom",
        )
        with self._config(oidc):
            resp = await self.client.get("/v1/auth/config")
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(
            resp.json(),
            {
                "issuer_url": "https://idp.example.com/realms/nebula",
                "client_id": "nebula-spa",
                "audience": "nebula-api",
                "scope": "openid profile email custom",
                "artifact_metadata_header_prefix": "x-amz-meta-",
            },
        )

    async def test_scope_placeholder_served_expanded(self):
        oidc = OidcConfig(
            issuer_url="https://idp.example.com/realms/nebula",
            client_id="nebula-spa",
            scope="openid api://{client_id}/access_as_user",
        )
        with self._config(oidc):
            resp = await self.client.get("/v1/auth/config")
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["scope"], "openid api://nebula-spa/access_as_user")
        self.assertEqual(body["audience"], "")

    async def test_blank_issuer_means_auth_disabled(self):
        with self._config(OidcConfig()):
            resp = await self.client.get("/v1/auth/config")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["issuer_url"], "")
        self.assertEqual(body["scope"], "openid profile email")

    async def test_serves_the_deployed_stores_metadata_prefix(self):
        """The SPA cannot guess it — an Azure deployment must say so."""
        with self._config(OidcConfig(), prefix="x-ms-meta-"):
            resp = await self.client.get("/v1/auth/config")
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["artifact_metadata_header_prefix"], "x-ms-meta-")

    async def test_open_without_token_when_auth_enabled(self):
        with patch("src.api.deps._oidc_enabled", return_value=True):
            resp = await self.client.get("/v1/auth/config")
        self.assertEqual(resp.status_code, 200, resp.text)
