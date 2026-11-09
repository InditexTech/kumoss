# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from src.clients.authz.models.access_evaluation_response import (
    AccessEvaluationResponse,
)
from src.clients.authz.models.action_name import ActionName
from src.domains.value_objects.token_claims import TokenClaims
from src.shared.constants import TerraformProvider
from src.shared.exceptions import ExceptionHandler


def _claims(**overrides) -> TokenClaims:
    defaults = dict(
        issuer="https://idp.test",
        subject="oidc-sub-1",
        email="alice@example.com",
        name="Alice",
        email_verified=True,
        properties={"issuer": "https://idp.test", "email": "alice@example.com"},
    )
    defaults.update(overrides)
    return TokenClaims(**defaults)


def _evaluate_args(**overrides):
    defaults = dict(
        scope_id="scope-1",
        provider=TerraformProvider.AZURE,
        repo_uri="https://dev.azure.com/org/proj/_git/repo",
    )
    defaults.update(overrides)
    return defaults


def _mock_authz_config(
    enabled: bool, endpoint: str = "http://authz:8083", timeout: float = 5.0
):
    cfg = MagicMock()
    cfg.enabled = enabled
    cfg.endpoint = endpoint
    cfg.token = "tok"
    cfg.timeout = timeout
    return cfg


class TestAuthzServiceClient(unittest.IsolatedAsyncioTestCase):
    @patch("src.infrastructure.external.authz_service.system_config")
    async def test_evaluate_disabled_returns_allow(self, mock_cfg):
        mock_cfg.services.authz = _mock_authz_config(enabled=False)
        from src.infrastructure.external.authz_service import (
            AuthzDecision,
            AuthzServiceClient,
        )

        result = await AuthzServiceClient().evaluate(
            _claims(), ActionName.GENERATE, **_evaluate_args()
        )
        self.assertEqual(result, AuthzDecision(allowed=True))

    @patch("src.infrastructure.external.authz_service.system_config")
    async def test_evaluate_enabled_without_endpoint_raises_503(self, mock_cfg):
        mock_cfg.services.authz = _mock_authz_config(enabled=True, endpoint="")
        from src.infrastructure.external.authz_service import AuthzServiceClient

        with self.assertRaises(ExceptionHandler) as ctx:
            await AuthzServiceClient().evaluate(
                _claims(), ActionName.GENERATE, **_evaluate_args()
            )
        self.assertEqual(ctx.exception.error_code, 503)

    @patch("src.infrastructure.external.authz_service.evaluate_op")
    @patch("src.infrastructure.external.authz_service.system_config")
    async def test_evaluate_timeout_raises_504(self, mock_cfg, mock_eval):
        mock_cfg.services.authz = _mock_authz_config(enabled=True)
        mock_eval.asyncio = AsyncMock(side_effect=httpx.ReadTimeout("timeout"))
        from src.infrastructure.external.authz_service import AuthzServiceClient

        with self.assertRaises(ExceptionHandler) as ctx:
            await AuthzServiceClient().evaluate(
                _claims(), ActionName.GENERATE, **_evaluate_args()
            )
        self.assertEqual(ctx.exception.error_code, 504)

    @patch("src.infrastructure.external.authz_service.evaluate_op")
    @patch("src.infrastructure.external.authz_service.system_config")
    async def test_evaluate_connection_error_raises_502(self, mock_cfg, mock_eval):
        mock_cfg.services.authz = _mock_authz_config(enabled=True)
        mock_eval.asyncio = AsyncMock(side_effect=httpx.ConnectError("unreachable"))
        from src.infrastructure.external.authz_service import AuthzServiceClient

        with self.assertRaises(ExceptionHandler) as ctx:
            await AuthzServiceClient().evaluate(
                _claims(), ActionName.GENERATE, **_evaluate_args()
            )
        self.assertEqual(ctx.exception.error_code, 502)

    @patch("src.infrastructure.external.authz_service.evaluate_op")
    @patch("src.infrastructure.external.authz_service.system_config")
    async def test_evaluate_unexpected_response_raises_502(self, mock_cfg, mock_eval):
        mock_cfg.services.authz = _mock_authz_config(enabled=True)
        mock_eval.asyncio = AsyncMock(return_value="not-a-response")
        from src.infrastructure.external.authz_service import AuthzServiceClient

        with self.assertRaises(ExceptionHandler) as ctx:
            await AuthzServiceClient().evaluate(
                _claims(), ActionName.GENERATE, **_evaluate_args()
            )
        self.assertEqual(ctx.exception.error_code, 502)

    @patch("src.infrastructure.external.authz_service.evaluate_op")
    @patch("src.infrastructure.external.authz_service.system_config")
    async def test_evaluate_missing_decision_raises_502(self, mock_cfg, mock_eval):
        mock_cfg.services.authz = _mock_authz_config(enabled=True)
        mock_eval.asyncio = AsyncMock(side_effect=KeyError("decision"))
        from src.infrastructure.external.authz_service import AuthzServiceClient

        with self.assertRaises(ExceptionHandler) as ctx:
            await AuthzServiceClient().evaluate(
                _claims(), ActionName.GENERATE, **_evaluate_args()
            )
        self.assertEqual(ctx.exception.error_code, 502)
        self.assertIn("unparseable", ctx.exception.message)

    @patch("src.infrastructure.external.authz_service.evaluate_op")
    @patch("src.infrastructure.external.authz_service.system_config")
    async def test_evaluate_non_json_body_raises_502(self, mock_cfg, mock_eval):
        mock_cfg.services.authz = _mock_authz_config(enabled=True)
        mock_eval.asyncio = AsyncMock(side_effect=json.JSONDecodeError("bad", "", 0))
        from src.infrastructure.external.authz_service import AuthzServiceClient

        with self.assertRaises(ExceptionHandler) as ctx:
            await AuthzServiceClient().evaluate(
                _claims(), ActionName.GENERATE, **_evaluate_args()
            )
        self.assertEqual(ctx.exception.error_code, 502)
        self.assertIn("unparseable", ctx.exception.message)

    @patch("src.infrastructure.external.authz_service.evaluate_op")
    @patch("src.infrastructure.external.authz_service.AuthenticatedClient")
    @patch("src.infrastructure.external.authz_service.system_config")
    async def test_evaluate_uses_config_timeout(
        self, mock_cfg, mock_client_cls, mock_eval
    ):
        mock_cfg.services.authz = _mock_authz_config(enabled=True, timeout=42.0)
        mock_eval.asyncio = AsyncMock(
            return_value=AccessEvaluationResponse(decision=True)
        )
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        from src.infrastructure.external.authz_service import AuthzServiceClient

        await AuthzServiceClient().evaluate(
            _claims(), ActionName.GENERATE, **_evaluate_args()
        )
        _, kwargs = mock_client_cls.call_args
        self.assertEqual(kwargs["timeout"], httpx.Timeout(42.0))

    @patch("src.infrastructure.external.authz_service.evaluate_op")
    @patch("src.infrastructure.external.authz_service.system_config")
    async def test_evaluate_allow_returns_authz_decision(self, mock_cfg, mock_eval):
        mock_cfg.services.authz = _mock_authz_config(enabled=True)
        mock_eval.asyncio = AsyncMock(
            return_value=AccessEvaluationResponse(decision=True)
        )
        from src.infrastructure.external.authz_service import (
            AuthzDecision,
            AuthzServiceClient,
        )

        result = await AuthzServiceClient().evaluate(
            _claims(),
            ActionName.GENERATE,
            **_evaluate_args(),
        )
        self.assertEqual(result, AuthzDecision(allowed=True))

    @patch("src.infrastructure.external.authz_service.evaluate_op")
    @patch("src.infrastructure.external.authz_service.system_config")
    async def test_evaluate_deny_returns_reason_user(self, mock_cfg, mock_eval):
        from src.clients.authz.models.response_context import ResponseContext
        from src.clients.authz.models.response_context_reason_user import (
            ResponseContextReasonUser,
        )

        reason_user = ResponseContextReasonUser.from_dict({"en": "No access"})
        mock_cfg.services.authz = _mock_authz_config(enabled=True)
        mock_eval.asyncio = AsyncMock(
            return_value=AccessEvaluationResponse(
                decision=False, context=ResponseContext(reason_user=reason_user)
            )
        )
        from src.infrastructure.external.authz_service import (
            AuthzDecision,
            AuthzServiceClient,
        )

        result = await AuthzServiceClient().evaluate(
            _claims(), ActionName.GENERATE, **_evaluate_args()
        )
        self.assertEqual(result, AuthzDecision(allowed=False, reason_user="No access"))

    @patch("src.infrastructure.external.authz_service.evaluate_op")
    @patch("src.infrastructure.external.authz_service.system_config")
    async def test_evaluate_deny_logs_reason_admin(self, mock_cfg, mock_eval):
        from src.clients.authz.models.response_context import ResponseContext
        from src.clients.authz.models.response_context_reason_admin import (
            ResponseContextReasonAdmin,
        )

        reason_admin = ResponseContextReasonAdmin.from_dict(
            {"en": "Policy OPA-42 denied"}
        )
        mock_cfg.services.authz = _mock_authz_config(enabled=True)
        mock_eval.asyncio = AsyncMock(
            return_value=AccessEvaluationResponse(
                decision=False, context=ResponseContext(reason_admin=reason_admin)
            )
        )
        from src.infrastructure.external.authz_service import AuthzServiceClient

        with self.assertLogs("src.shared.logger._logger", level="WARNING") as cm:
            await AuthzServiceClient().evaluate(
                _claims(), ActionName.GENERATE, **_evaluate_args()
            )
        self.assertTrue(any("OPA-42" in line for line in cm.output))

    @patch("src.infrastructure.external.authz_service.evaluate_op")
    @patch("src.infrastructure.external.authz_service.system_config")
    async def test_evaluate_builds_correct_subject(self, mock_cfg, mock_eval):
        mock_cfg.services.authz = _mock_authz_config(enabled=True)
        mock_eval.asyncio = AsyncMock(
            return_value=AccessEvaluationResponse(decision=True)
        )
        from src.infrastructure.external.authz_service import AuthzServiceClient

        await AuthzServiceClient().evaluate(
            _claims(), ActionName.GENERATE, **_evaluate_args()
        )
        request = mock_eval.asyncio.call_args.kwargs["body"]
        self.assertEqual(request.subject.id, "https://idp.test")
        props_dict = request.subject.properties.to_dict()
        self.assertEqual(props_dict["issuer"], "https://idp.test")
        self.assertEqual(props_dict["email"], "alice@example.com")

    @patch("src.infrastructure.external.authz_service.evaluate_op")
    @patch("src.infrastructure.external.authz_service.system_config")
    async def test_evaluate_strips_email_when_unverified(self, mock_cfg, mock_eval):
        from src.clients.authz.types import UNSET

        mock_cfg.services.authz = _mock_authz_config(enabled=True)
        mock_eval.asyncio = AsyncMock(
            return_value=AccessEvaluationResponse(decision=True)
        )
        from src.infrastructure.external.authz_service import AuthzServiceClient

        await AuthzServiceClient().evaluate(
            _claims(email_verified=False), ActionName.GENERATE, **_evaluate_args()
        )
        request = mock_eval.asyncio.call_args.kwargs["body"]
        self.assertIs(request.subject.properties.email, UNSET)

    @patch("src.infrastructure.external.authz_service.evaluate_op")
    @patch("src.infrastructure.external.authz_service.system_config")
    async def test_evaluate_maps_provider_to_resource_properties(
        self, mock_cfg, mock_eval
    ):
        from src.clients.authz.models.resource_properties_provider import (
            ResourcePropertiesProvider,
        )

        mock_cfg.services.authz = _mock_authz_config(enabled=True)
        mock_eval.asyncio = AsyncMock(
            return_value=AccessEvaluationResponse(decision=True)
        )
        from src.infrastructure.external.authz_service import AuthzServiceClient

        await AuthzServiceClient().evaluate(
            _claims(),
            ActionName.GENERATE,
            **_evaluate_args(provider=TerraformProvider.GCP),
        )
        request = mock_eval.asyncio.call_args.kwargs["body"]
        self.assertEqual(
            request.resource.properties.provider, ResourcePropertiesProvider.GCP
        )

    @patch("src.infrastructure.external.authz_service.evaluate_op")
    @patch("src.infrastructure.external.authz_service.system_config")
    async def test_evaluate_omits_root_module_path_when_none(self, mock_cfg, mock_eval):
        from src.clients.authz.types import UNSET

        mock_cfg.services.authz = _mock_authz_config(enabled=True)
        mock_eval.asyncio = AsyncMock(
            return_value=AccessEvaluationResponse(decision=True)
        )
        from src.infrastructure.external.authz_service import AuthzServiceClient

        await AuthzServiceClient().evaluate(
            _claims(),
            ActionName.GENERATE,
            **_evaluate_args(),
            root_module_path=None,
        )
        request = mock_eval.asyncio.call_args.kwargs["body"]
        self.assertIs(request.resource.properties.root_module_path, UNSET)
