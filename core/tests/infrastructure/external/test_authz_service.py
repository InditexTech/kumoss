# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from src.clients.authz.models.access_evaluation_request import (
    AccessEvaluationRequest,
)
from src.clients.authz.models.access_evaluation_response import (
    AccessEvaluationResponse,
)
from src.clients.authz.models.action import Action
from src.clients.authz.models.action_name import ActionName
from src.clients.authz.models.resource import Resource
from src.clients.authz.models.resource_type import ResourceType
from src.clients.authz.models.subject import Subject
from src.clients.authz.models.subject_type import SubjectType
from src.shared.exceptions import ExceptionHandler


def _minimal_request() -> AccessEvaluationRequest:
    return AccessEvaluationRequest(
        subject=Subject(type_=SubjectType.USER, id="u1"),
        action=Action(name=ActionName.GENERATE),
        resource=Resource(type_=ResourceType.SCOPE, id="scope-1"),
    )


def _mock_authz_config(enabled: bool, endpoint: str = "http://authz:8083", timeout: float = 5.0):
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
        from src.infrastructure.external.authz_service import AuthzServiceClient

        result = await AuthzServiceClient().evaluate(_minimal_request())
        self.assertTrue(result.decision)

    @patch("src.infrastructure.external.authz_service.evaluate_op")
    @patch("src.infrastructure.external.authz_service.system_config")
    async def test_evaluate_returns_decision_true(self, mock_cfg, mock_eval):
        mock_cfg.services.authz = _mock_authz_config(enabled=True)
        mock_eval.asyncio = AsyncMock(
            return_value=AccessEvaluationResponse(decision=True)
        )
        from src.infrastructure.external.authz_service import AuthzServiceClient

        result = await AuthzServiceClient().evaluate(_minimal_request())
        self.assertTrue(result.decision)

    @patch("src.infrastructure.external.authz_service.evaluate_op")
    @patch("src.infrastructure.external.authz_service.system_config")
    async def test_evaluate_timeout_raises_504(self, mock_cfg, mock_eval):
        mock_cfg.services.authz = _mock_authz_config(enabled=True)
        mock_eval.asyncio = AsyncMock(side_effect=httpx.ReadTimeout("timeout"))
        from src.infrastructure.external.authz_service import AuthzServiceClient

        with self.assertRaises(ExceptionHandler) as ctx:
            await AuthzServiceClient().evaluate(_minimal_request())
        self.assertEqual(ctx.exception.error_code, 504)

    @patch("src.infrastructure.external.authz_service.evaluate_op")
    @patch("src.infrastructure.external.authz_service.system_config")
    async def test_evaluate_connection_error_raises_502(self, mock_cfg, mock_eval):
        mock_cfg.services.authz = _mock_authz_config(enabled=True)
        mock_eval.asyncio = AsyncMock(
            side_effect=httpx.ConnectError("unreachable")
        )
        from src.infrastructure.external.authz_service import AuthzServiceClient

        with self.assertRaises(ExceptionHandler) as ctx:
            await AuthzServiceClient().evaluate(_minimal_request())
        self.assertEqual(ctx.exception.error_code, 502)

    @patch("src.infrastructure.external.authz_service.evaluate_op")
    @patch("src.infrastructure.external.authz_service.system_config")
    async def test_evaluate_unexpected_response_raises_502(self, mock_cfg, mock_eval):
        mock_cfg.services.authz = _mock_authz_config(enabled=True)
        mock_eval.asyncio = AsyncMock(return_value="not-a-response")
        from src.infrastructure.external.authz_service import AuthzServiceClient

        with self.assertRaises(ExceptionHandler) as ctx:
            await AuthzServiceClient().evaluate(_minimal_request())
        self.assertEqual(ctx.exception.error_code, 502)

    @patch("src.infrastructure.external.authz_service.evaluate_op")
    @patch("src.infrastructure.external.authz_service.AuthenticatedClient")
    @patch("src.infrastructure.external.authz_service.system_config")
    async def test_evaluate_uses_config_timeout(self, mock_cfg, mock_client_cls, mock_eval):
        mock_cfg.services.authz = _mock_authz_config(enabled=True, timeout=42.0)
        mock_eval.asyncio = AsyncMock(
            return_value=AccessEvaluationResponse(decision=True)
        )
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        from src.infrastructure.external.authz_service import AuthzServiceClient

        await AuthzServiceClient().evaluate(_minimal_request())
        _, kwargs = mock_client_cls.call_args
        self.assertEqual(kwargs["timeout"], httpx.Timeout(42.0))
