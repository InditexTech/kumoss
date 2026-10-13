# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Validation and scope interpolation tests for OidcConfig."""

import unittest

from pydantic import ValidationError

from src.shared.config.system_config import OidcConfig


class TestOidcConfig(unittest.TestCase):
    def test_scope_placeholder_expands_to_client_id(self):
        cfg = OidcConfig(
            issuer_url="https://idp.example.com",
            client_id="kumoss-spa",
            scope="openid profile email api://{client_id}/access_as_user",
        )
        self.assertEqual(
            cfg.scope, "openid profile email api://kumoss-spa/access_as_user"
        )

    def test_repeated_placeholders_all_expand(self):
        cfg = OidcConfig(
            issuer_url="https://idp.example.com",
            client_id="abc",
            scope="api://{client_id}/read api://{client_id}/write",
        )
        self.assertEqual(cfg.scope, "api://abc/read api://abc/write")

    def test_scope_without_placeholder_is_untouched(self):
        cfg = OidcConfig()
        self.assertEqual(cfg.scope, "openid profile email")

    def test_entra_issuer_gets_default_api_scope(self):
        cfg = OidcConfig(
            issuer_url="https://login.microsoftonline.com/tenant-id/v2.0",
            client_id="entra-app",
        )
        self.assertEqual(cfg.scope, "openid profile email api://entra-app/.default")

    def test_entra_issuer_custom_scope_is_not_overridden(self):
        cfg = OidcConfig(
            issuer_url="https://login.microsoftonline.com/tenant-id/v2.0",
            client_id="entra-app",
            scope="openid profile email api://{client_id}/access_as_user",
        )
        self.assertEqual(
            cfg.scope, "openid profile email api://entra-app/access_as_user"
        )

    def test_non_entra_issuer_keeps_default_scope(self):
        cfg = OidcConfig(
            issuer_url="https://keycloak.example.com/realms/kumoss",
            client_id="kumoss-spa",
        )
        self.assertEqual(cfg.scope, "openid profile email")

    def test_stray_braces_survive(self):
        cfg = OidcConfig(
            issuer_url="https://idp.example.com",
            client_id="abc",
            scope="openid {custom} api://{client_id}/x",
        )
        self.assertEqual(cfg.scope, "openid {custom} api://abc/x")

    def test_placeholder_with_blank_client_id_is_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            OidcConfig(scope="openid api://{client_id}/x")
        self.assertIn("oidc.scope references {client_id}", str(ctx.exception))

    def test_issuer_without_client_id_is_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            OidcConfig(issuer_url="https://idp.example.com")
        self.assertIn("oidc.client_id is empty", str(ctx.exception))

    def test_audience_defaults_to_blank(self):
        cfg = OidcConfig(issuer_url="https://idp.example.com", client_id="kumoss-spa")
        self.assertEqual(cfg.audience, "")


if __name__ == "__main__":
    unittest.main()
