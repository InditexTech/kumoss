# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Verify every write route calls ``authorize`` with the correct action.

These tests patch ``authorize`` (the PEP helper) at its call site and
confirm each route invokes it with the expected ``action`` string and
that authorization parameters come from the session context for
session-scoped routes, not from user input.
"""

import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from src.api.v1.terraform import _resolve_or_raise
from src.application.iac_requests import (
    ApplyRequest,
    GenerateRequest,
    ImportRequest,
)
from src.domains.entities import SessionContext, User
from src.domains.value_objects.token_claims import TokenClaims
from src.shared.constants import OperationType, TerraformProvider


def _user(pk: int = 1) -> User:
    from datetime import UTC, datetime

    from src.shared.constants import OperationRole

    return User(
        id=pk,
        issuer="urn:test",
        subject=f"sub-{pk}",
        email=f"u{pk}@example.com",
        display_name=f"User {pk}",
        operation_role=OperationRole.DEVOPS,
        panel_role=None,
        created_at=datetime.now(UTC),
    )


def _claims() -> TokenClaims:
    return TokenClaims(
        issuer="urn:test",
        subject="sub-1",
        email="u1@example.com",
        name="User 1",
        email_verified=True,
    )


def _session_ctx(sid=None) -> SessionContext:
    return SessionContext(
        id=sid or uuid4(),
        user_id="1",
        round_id=1,
        repo_uri="https://dev.azure.com/org/proj/_git/repo",
        terraform_prv=TerraformProvider.AZURE,
        branch_name="Kumoss/x",
        scope_id="sub-123",
        iac_path="infra",
        operation_type=OperationType.GENERATE,
        history=[],
        chat_history=[],
    )


class TestResolveOrRaiseFirstCall(unittest.IsolatedAsyncioTestCase):
    """First-call path: request has repo_uri, authorize uses request body."""

    @patch("src.api.v1.terraform.authorize", new_callable=AsyncMock)
    @patch("src.api.v1.terraform._orchestration")
    @patch("src.api.v1.terraform._workspace")
    async def test_generate_passes_action_generate(
        self, mock_ws, mock_orch, mock_authz
    ):
        mock_ws.validate_uri = AsyncMock()
        mock_orch.resolve = AsyncMock(return_value=_session_ctx())
        request = GenerateRequest(
            repo_uri="https://dev.azure.com/org/proj/_git/repo",
            terraform_providers=TerraformProvider.AZURE,
            scope_id="sub-123",
            iac_path="infra",
            q="create a resource group",
        )
        await _resolve_or_raise(
            request, _user(), _claims(), OperationType.GENERATE, action="generate"
        )
        mock_authz.assert_called_once()
        call_kwargs = mock_authz.call_args
        self.assertEqual(call_kwargs[0][1], "generate")
        self.assertEqual(call_kwargs.kwargs["scope_id"], "sub-123")
        self.assertEqual(call_kwargs.kwargs["provider"], TerraformProvider.AZURE)

    @patch("src.api.v1.terraform.authorize", new_callable=AsyncMock)
    @patch("src.api.v1.terraform._orchestration")
    @patch("src.api.v1.terraform._workspace")
    async def test_drift_passes_action_drift(self, mock_ws, mock_orch, mock_authz):
        mock_ws.validate_uri = AsyncMock()
        mock_orch.resolve = AsyncMock(return_value=_session_ctx())
        request = GenerateRequest(
            repo_uri="https://dev.azure.com/org/proj/_git/repo",
            terraform_providers=TerraformProvider.GCP,
            scope_id="proj-456",
            iac_path="",
            q="check drift",
        )
        await _resolve_or_raise(
            request, _user(), _claims(), OperationType.DRIFT, action="drift"
        )
        mock_authz.assert_called_once()
        self.assertEqual(mock_authz.call_args[0][1], "drift")
        self.assertEqual(mock_authz.call_args.kwargs["provider"], TerraformProvider.GCP)

    @patch("src.api.v1.terraform.authorize", new_callable=AsyncMock)
    @patch("src.api.v1.terraform._orchestration")
    @patch("src.api.v1.terraform._workspace")
    async def test_import_passes_action_import(self, mock_ws, mock_orch, mock_authz):
        mock_ws.validate_uri = AsyncMock()
        mock_orch.resolve = AsyncMock(return_value=_session_ctx())
        request = ImportRequest(
            repo_uri="https://dev.azure.com/org/proj/_git/repo",
            terraform_providers=TerraformProvider.AWS,
            scope_id="acct-789",
            iac_path="modules/vpc",
            q="import vpc",
        )
        await _resolve_or_raise(
            request, _user(), _claims(), OperationType.IMPORT, action="import"
        )
        mock_authz.assert_called_once()
        self.assertEqual(mock_authz.call_args[0][1], "import")


class TestResolveOrRaiseSessionOnly(unittest.IsolatedAsyncioTestCase):
    """Session-only path: authorize reads from SessionContext, not request."""

    @patch("src.api.v1.terraform.authorize", new_callable=AsyncMock)
    @patch("src.api.v1.terraform._orchestration")
    @patch("src.api.v1.terraform.assert_session_access", new_callable=AsyncMock)
    async def test_apply_passes_action_apply_from_session(
        self, mock_access, mock_orch, mock_authz
    ):
        sid = uuid4()
        ctx = _session_ctx(sid)
        mock_orch.resolve = AsyncMock(return_value=ctx)
        request = ApplyRequest(session_id=sid)
        await _resolve_or_raise(request, _user(), _claims(), action="apply")
        mock_authz.assert_called_once()
        self.assertEqual(mock_authz.call_args[0][1], "apply")
        self.assertEqual(mock_authz.call_args.kwargs["scope_id"], ctx.scope_id)
        self.assertEqual(
            mock_authz.call_args.kwargs["provider"], TerraformProvider.AZURE
        )
        self.assertEqual(mock_authz.call_args.kwargs["repo_uri"], ctx.repo_uri)
        self.assertEqual(mock_authz.call_args.kwargs["session_id"], ctx.id)

    @patch("src.api.v1.terraform.authorize", new_callable=AsyncMock)
    @patch("src.api.v1.terraform._orchestration")
    @patch("src.api.v1.terraform.assert_session_access", new_callable=AsyncMock)
    async def test_iteration_uses_session_operation_as_action(
        self, mock_access, mock_orch, mock_authz
    ):
        sid = uuid4()
        ctx = _session_ctx(sid)
        mock_orch.resolve = AsyncMock(return_value=ctx)
        request = GenerateRequest(
            session_id=sid,
            q="continue",
        )
        await _resolve_or_raise(
            request, _user(), _claims(), OperationType.GENERATE, action="generate"
        )
        mock_authz.assert_called_once()
        self.assertEqual(mock_authz.call_args[0][1], "generate")
        self.assertTrue(mock_authz.call_args.kwargs["iteration"])

    @patch("src.api.v1.terraform.authorize", new_callable=AsyncMock)
    @patch("src.api.v1.terraform._orchestration")
    @patch("src.api.v1.terraform.assert_session_access", new_callable=AsyncMock)
    async def test_authz_deny_raises_403(self, mock_access, mock_orch, mock_authz):
        from fastapi import HTTPException

        sid = uuid4()
        mock_orch.resolve = AsyncMock(return_value=_session_ctx(sid))
        mock_authz.side_effect = HTTPException(status_code=403, detail="Denied")
        request = ApplyRequest(session_id=sid)
        with self.assertRaises(HTTPException) as cm:
            await _resolve_or_raise(request, _user(), _claims(), action="apply")
        self.assertEqual(cm.exception.status_code, 403)
