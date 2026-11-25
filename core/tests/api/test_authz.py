# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from src.clients.authz.models.action_name import ActionName
from src.domains.value_objects.token_claims import TokenClaims
from src.infrastructure.external.authz_service import AuthzDecision
from src.domains.value_objects.provider_scope import ProviderScope
from src.shared.exceptions import ExceptionHandler


def _claims(**overrides) -> TokenClaims:
    defaults = dict(
        issuer="https://idp.test",
        subject="oidc-sub-1",
        email="alice@example.com",
        name="Alice",
        email_verified=True,
        properties={
            "issuer": "https://idp.test",
            "email": "alice@example.com",
        },
    )
    defaults.update(overrides)
    return TokenClaims(**defaults)


_AUTHZ_ARGS = dict(
    scope_id="scope-1",
    provider="azurerm",
    repo_uri="https://dev.azure.com/org/project/_git/repo",
)


class TestAuthorize(unittest.IsolatedAsyncioTestCase):
    @patch("src.api.authz.AuthzServiceClient")
    async def test_authorize_allow_passes_silently(self, mock_cls):
        mock_cls.return_value.evaluate = AsyncMock(
            return_value=AuthzDecision(allowed=True)
        )
        from src.api.authz import authorize

        await authorize(_claims(), ActionName.GENERATE, **_AUTHZ_ARGS)

    @patch("src.api.authz.AuthzServiceClient")
    async def test_authorize_deny_raises_403(self, mock_cls):
        mock_cls.return_value.evaluate = AsyncMock(
            return_value=AuthzDecision(allowed=False)
        )
        from src.api.authz import authorize

        with self.assertRaises(HTTPException) as ctx:
            await authorize(_claims(), ActionName.GENERATE, **_AUTHZ_ARGS)
        self.assertEqual(ctx.exception.status_code, 403)

    @patch("src.api.authz.AuthzServiceClient")
    async def test_authorize_deny_includes_reason_user(self, mock_cls):
        mock_cls.return_value.evaluate = AsyncMock(
            return_value=AuthzDecision(
                allowed=False, reason_user="You lack permission for this scope"
            )
        )
        from src.api.authz import authorize

        with self.assertRaises(HTTPException) as ctx:
            await authorize(_claims(), ActionName.GENERATE, **_AUTHZ_ARGS)
        self.assertIn("You lack permission", ctx.exception.detail)

    @patch("src.api.authz.AuthzServiceClient")
    async def test_authorize_deny_defaults_to_access_denied(self, mock_cls):
        mock_cls.return_value.evaluate = AsyncMock(
            return_value=AuthzDecision(allowed=False, reason_user=None)
        )
        from src.api.authz import authorize

        with self.assertRaises(HTTPException) as ctx:
            await authorize(_claims(), ActionName.GENERATE, **_AUTHZ_ARGS)
        self.assertEqual(ctx.exception.detail, "Access denied")

    @patch("src.api.authz.AuthzServiceClient")
    async def test_authorize_pdp_502_raises_502(self, mock_cls):
        mock_cls.return_value.evaluate = AsyncMock(
            side_effect=ExceptionHandler("PDP unreachable", 502)
        )
        from src.api.authz import authorize

        with self.assertRaises(HTTPException) as ctx:
            await authorize(_claims(), ActionName.GENERATE, **_AUTHZ_ARGS)
        self.assertEqual(ctx.exception.status_code, 502)

    @patch("src.api.authz.AuthzServiceClient")
    async def test_authorize_pdp_504_raises_504(self, mock_cls):
        mock_cls.return_value.evaluate = AsyncMock(
            side_effect=ExceptionHandler("PDP timed out", 504)
        )
        from src.api.authz import authorize

        with self.assertRaises(HTTPException) as ctx:
            await authorize(_claims(), ActionName.GENERATE, **_AUTHZ_ARGS)
        self.assertEqual(ctx.exception.status_code, 504)


_REPO = "https://dev.azure.com/org/project/_git/repo"


class TestAuthorizeProviders(unittest.IsolatedAsyncioTestCase):
    @patch("src.api.authz.AuthzServiceClient")
    async def test_one_evaluation_per_scoped_pair(self, mock_cls):
        evaluate = AsyncMock(return_value=AuthzDecision(allowed=True))
        mock_cls.return_value.evaluate = evaluate
        from src.api.authz import authorize_providers

        await authorize_providers(
            _claims(),
            ActionName.GENERATE,
            providers=(
                ProviderScope("azurerm", "sub-1"),
                ProviderScope("random"),
                ProviderScope("google", "proj-1"),
            ),
            repo_uri=_REPO,
            root_module_path="envs/prod",
        )

        self.assertEqual(evaluate.await_count, 2)
        calls = [c.kwargs for c in evaluate.await_args_list]
        self.assertEqual(
            [(c["scope_id"], c["provider"]) for c in calls],
            [("sub-1", "azurerm"), ("proj-1", "google")],
        )
        for c in calls:
            self.assertEqual(c["repo_uri"], _REPO)
            self.assertEqual(c["root_module_path"], "envs/prod")

    @patch("src.api.authz.AuthzServiceClient")
    async def test_no_scoped_pair_evaluates_once_at_module_level(self, mock_cls):
        evaluate = AsyncMock(return_value=AuthzDecision(allowed=True))
        mock_cls.return_value.evaluate = evaluate
        from src.api.authz import authorize_providers

        await authorize_providers(
            _claims(),
            ActionName.DRIFT,
            providers=(ProviderScope("random"), ProviderScope("kubernetes")),
            repo_uri=_REPO,
        )

        evaluate.assert_awaited_once()
        kwargs = evaluate.await_args.kwargs
        self.assertEqual(kwargs["scope_id"], "")
        self.assertIsNone(kwargs["provider"])

    @patch("src.api.authz.AuthzServiceClient")
    async def test_empty_providers_evaluates_once_at_module_level(self, mock_cls):
        evaluate = AsyncMock(return_value=AuthzDecision(allowed=True))
        mock_cls.return_value.evaluate = evaluate
        from src.api.authz import authorize_providers

        await authorize_providers(
            _claims(), ActionName.GENERATE, providers=(), repo_uri=_REPO
        )

        evaluate.assert_awaited_once()
        self.assertIsNone(evaluate.await_args.kwargs["provider"])

    @patch("src.api.authz.AuthzServiceClient")
    async def test_any_denied_pair_raises_403_and_stops(self, mock_cls):
        evaluate = AsyncMock(
            side_effect=[
                AuthzDecision(allowed=False, reason_user="no access to sub-1"),
                AuthzDecision(allowed=True),
            ]
        )
        mock_cls.return_value.evaluate = evaluate
        from src.api.authz import authorize_providers

        with self.assertRaises(HTTPException) as ctx:
            await authorize_providers(
                _claims(),
                ActionName.GENERATE,
                providers=(
                    ProviderScope("azurerm", "sub-1"),
                    ProviderScope("google", "proj-1"),
                ),
                repo_uri=_REPO,
            )
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertIn("sub-1", ctx.exception.detail)
        self.assertEqual(evaluate.await_count, 1)
