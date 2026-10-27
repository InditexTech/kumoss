# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import logging
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from src.clients.authz.models.access_evaluation_response import (
    AccessEvaluationResponse,
)
from src.clients.authz.models.response_context import ResponseContext
from src.clients.authz.models.response_context_reason_admin import (
    ResponseContextReasonAdmin,
)
from src.clients.authz.models.response_context_reason_user import (
    ResponseContextReasonUser,
)
from src.domains.value_objects.token_claims import TokenClaims
from src.shared.constants import TerraformProvider
from src.shared.exceptions import ExceptionHandler


def _claims(**overrides) -> TokenClaims:
    defaults = dict(
        issuer="https://idp.test",
        subject="user-1",
        email="alice@example.com",
        name="Alice",
        email_verified=True,
        groups=["team-a"],
    )
    defaults.update(overrides)
    return TokenClaims(**defaults)


class TestAuthorize(unittest.IsolatedAsyncioTestCase):
    @patch("src.api.authz.AuthzServiceClient")
    async def test_authorize_allow_passes_silently(self, mock_cls):
        mock_cls.return_value.evaluate = AsyncMock(
            return_value=AccessEvaluationResponse(decision=True)
        )
        from src.api.authz import authorize

        await authorize(
            _claims(),
            "generate",
            scope_id="scope-1",
            provider=TerraformProvider.AZURE,
            repo_uri="https://dev.azure.com/org/project/_git/repo",
        )

    @patch("src.api.authz.AuthzServiceClient")
    async def test_authorize_deny_raises_403(self, mock_cls):
        mock_cls.return_value.evaluate = AsyncMock(
            return_value=AccessEvaluationResponse(decision=False)
        )
        from src.api.authz import authorize

        with self.assertRaises(HTTPException) as ctx:
            await authorize(
                _claims(),
                "generate",
                scope_id="scope-1",
                provider=TerraformProvider.AZURE,
                repo_uri="https://dev.azure.com/org/project/_git/repo",
            )
        self.assertEqual(ctx.exception.status_code, 403)

    @patch("src.api.authz.AuthzServiceClient")
    async def test_authorize_deny_includes_reason_user(self, mock_cls):
        reason_user = ResponseContextReasonUser.from_dict(
            {"en": "You lack permission for this scope"}
        )
        resp_ctx = ResponseContext(reason_user=reason_user)
        mock_cls.return_value.evaluate = AsyncMock(
            return_value=AccessEvaluationResponse(decision=False, context=resp_ctx)
        )
        from src.api.authz import authorize

        with self.assertRaises(HTTPException) as ctx:
            await authorize(
                _claims(),
                "generate",
                scope_id="scope-1",
                provider=TerraformProvider.AZURE,
                repo_uri="https://dev.azure.com/org/project/_git/repo",
            )
        self.assertIn("You lack permission", ctx.exception.detail)

    @patch("src.api.authz.AuthzServiceClient")
    async def test_authorize_deny_logs_reason_admin(self, mock_cls):
        reason_admin = ResponseContextReasonAdmin.from_dict(
            {"en": "Policy OPA-42 denied"}
        )
        resp_ctx = ResponseContext(reason_admin=reason_admin)
        mock_cls.return_value.evaluate = AsyncMock(
            return_value=AccessEvaluationResponse(decision=False, context=resp_ctx)
        )
        from src.api.authz import authorize

        with self.assertLogs("src.api.authz", level=logging.WARNING) as cm:
            with self.assertRaises(HTTPException):
                await authorize(
                    _claims(),
                    "generate",
                    scope_id="scope-1",
                    provider=TerraformProvider.AZURE,
                    repo_uri="https://dev.azure.com/org/project/_git/repo",
                )
        self.assertTrue(any("OPA-42" in line for line in cm.output))

    @patch("src.api.authz.AuthzServiceClient")
    async def test_authorize_builds_correct_subject(self, mock_cls):
        mock_cls.return_value.evaluate = AsyncMock(
            return_value=AccessEvaluationResponse(decision=True)
        )
        from src.api.authz import authorize

        await authorize(
            _claims(),
            "generate",
            scope_id="scope-1",
            provider=TerraformProvider.AZURE,
            repo_uri="https://dev.azure.com/org/project/_git/repo",
        )
        call_args = mock_cls.return_value.evaluate.call_args
        request = call_args.args[0]
        self.assertEqual(request.subject.id, "user-1")
        self.assertEqual(request.subject.properties.issuer, "https://idp.test")
        self.assertEqual(request.subject.properties.email, "alice@example.com")
        self.assertEqual(request.subject.properties.groups, ["team-a"])

    @patch("src.api.authz.AuthzServiceClient")
    async def test_authorize_omits_email_when_not_verified(self, mock_cls):
        mock_cls.return_value.evaluate = AsyncMock(
            return_value=AccessEvaluationResponse(decision=True)
        )
        from src.api.authz import authorize
        from src.clients.authz.types import UNSET

        await authorize(
            _claims(email_verified=False),
            "generate",
            scope_id="scope-1",
            provider=TerraformProvider.AZURE,
            repo_uri="https://dev.azure.com/org/project/_git/repo",
        )
        request = mock_cls.return_value.evaluate.call_args.args[0]
        self.assertIs(request.subject.properties.email, UNSET)

    @patch("src.api.authz.AuthzServiceClient")
    async def test_authorize_omits_groups_when_empty(self, mock_cls):
        mock_cls.return_value.evaluate = AsyncMock(
            return_value=AccessEvaluationResponse(decision=True)
        )
        from src.api.authz import authorize
        from src.clients.authz.types import UNSET

        await authorize(
            _claims(groups=[]),
            "generate",
            scope_id="scope-1",
            provider=TerraformProvider.AZURE,
            repo_uri="https://dev.azure.com/org/project/_git/repo",
        )
        request = mock_cls.return_value.evaluate.call_args.args[0]
        self.assertIs(request.subject.properties.groups, UNSET)

    @patch("src.api.authz.AuthzServiceClient")
    async def test_authorize_omits_iac_path_when_empty(self, mock_cls):
        mock_cls.return_value.evaluate = AsyncMock(
            return_value=AccessEvaluationResponse(decision=True)
        )
        from src.api.authz import authorize
        from src.clients.authz.types import UNSET

        await authorize(
            _claims(),
            "generate",
            scope_id="scope-1",
            provider=TerraformProvider.AZURE,
            repo_uri="https://dev.azure.com/org/project/_git/repo",
            iac_path=None,
        )
        request = mock_cls.return_value.evaluate.call_args.args[0]
        self.assertIs(request.resource.properties.iac_path, UNSET)

    @patch("src.api.authz.AuthzServiceClient")
    async def test_authorize_pdp_502_raises_502(self, mock_cls):
        mock_cls.return_value.evaluate = AsyncMock(
            side_effect=ExceptionHandler("PDP unreachable", 502)
        )
        from src.api.authz import authorize

        with self.assertRaises(HTTPException) as ctx:
            await authorize(
                _claims(),
                "generate",
                scope_id="scope-1",
                provider=TerraformProvider.AZURE,
                repo_uri="https://dev.azure.com/org/project/_git/repo",
            )
        self.assertEqual(ctx.exception.status_code, 502)
