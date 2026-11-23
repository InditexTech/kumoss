# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Verify every write route authorizes with the correct ActionName.

These tests patch ``authorize_providers`` (the PEP helper) at its call
site. Iteration calls authorize up front on the providers and scopes
recorded on the session; first calls authorize inside the session runner
(``_Inputs.authorizer``), once the root module's manifest says which
providers and scopes the session uses. Never from user input.
"""

import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from fastapi import HTTPException

from src.api.v1.terraform import _Inputs, _make_runner, _resolve_or_raise
from src.application.iac_requests import (
    ApplyRequest,
    GenerateRequest,
    ImportRequest,
    ManifestAnswers,
)
from src.clients.authz.models.action_name import ActionName
from src.domains.entities import SessionContext, User
from src.domains.value_objects import ProviderScope
from src.domains.value_objects.token_claims import TokenClaims
from src.shared.constants import OperationType
from src.shared.exceptions import ExceptionHandler


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


PROVIDERS = (ProviderScope("azurerm", "sub-123"), ProviderScope("random"))


def _session_ctx(sid=None, operation=OperationType.GENERATE) -> SessionContext:
    return SessionContext(
        id=sid or uuid4(),
        user_id="1",
        round_id=1,
        repo_uri="https://dev.azure.com/org/proj/_git/repo",
        providers=PROVIDERS,
        branch_name="Kumoss/x",
        root_module_path="infra",
        operation_type=operation,
        history=[],
        chat_history=[],
    )


class TestResolveOrRaiseFirstCall(unittest.IsolatedAsyncioTestCase):
    """First-call path: nothing is authorized before the session runs.

    The request no longer names providers or scopes; they come from the
    root module's manifest and are authorized during the session setup.
    """

    async def _first_call(self, request, operation: OperationType):
        with (
            patch(
                "src.api.v1.terraform.authorize_providers", new_callable=AsyncMock
            ) as mock_authz,
            patch("src.api.v1.terraform._orchestration") as mock_orch,
            patch("src.api.v1.terraform._workspace") as mock_ws,
        ):
            mock_ws.validate_uri = AsyncMock()
            ctx = _session_ctx(operation=operation)
            mock_orch.resolve = AsyncMock(return_value=ctx)
            got = await _resolve_or_raise(request, _user(), _claims(), operation)
        self.assertIs(got, ctx)
        mock_ws.validate_uri.assert_awaited_once_with(ctx.repo_uri)
        mock_authz.assert_not_called()

    async def test_generate_defers_authz_to_the_session_setup(self):
        await self._first_call(
            GenerateRequest(
                repo_uri="https://dev.azure.com/org/proj/_git/repo",
                root_module_path="infra",
                q="create a resource group",
            ),
            OperationType.GENERATE,
        )

    async def test_drift_defers_authz_to_the_session_setup(self):
        await self._first_call(
            GenerateRequest(
                repo_uri="https://dev.azure.com/org/proj/_git/repo",
                root_module_path="",
                q="check drift",
            ),
            OperationType.DRIFT,
        )

    async def test_import_defers_authz_to_the_session_setup(self):
        await self._first_call(
            ImportRequest(
                repo_uri="https://dev.azure.com/org/proj/_git/repo",
                root_module_path="modules/vpc",
                q="import vpc",
            ),
            OperationType.IMPORT,
        )

    @patch("src.api.v1.terraform.authorize_providers", new_callable=AsyncMock)
    @patch("src.api.v1.terraform._orchestration")
    @patch("src.api.v1.terraform._workspace")
    async def test_unreachable_repo_on_first_call_creates_no_session(
        self, mock_ws, mock_orch, mock_authz
    ):
        from fastapi import HTTPException

        from src.infrastructure.exceptions import RepositoryUnreachable

        mock_ws.validate_uri = AsyncMock(side_effect=RepositoryUnreachable(400))
        mock_orch.resolve = AsyncMock(return_value=_session_ctx())
        request = GenerateRequest(
            repo_uri="https://dev.azure.com/org/proj/_git/repo",
            q="create a resource group",
        )
        with self.assertRaises(HTTPException) as cm:
            await _resolve_or_raise(request, _user(), _claims(), OperationType.GENERATE)
        self.assertEqual(cm.exception.status_code, 400)
        mock_authz.assert_not_awaited()
        mock_orch.resolve.assert_not_awaited()


class TestResolveOrRaiseSessionOnly(unittest.IsolatedAsyncioTestCase):
    """Session-only path: authorize reads from SessionContext, not request."""

    @patch("src.api.v1.terraform.authorize_providers", new_callable=AsyncMock)
    @patch("src.api.v1.terraform._workspace")
    @patch("src.api.v1.terraform._orchestration")
    @patch("src.api.v1.terraform.assert_session_access", new_callable=AsyncMock)
    async def test_apply_passes_action_apply_from_session(
        self, mock_access, mock_orch, mock_ws, mock_authz
    ):
        mock_ws.validate_uri = AsyncMock()
        sid = uuid4()
        ctx = _session_ctx(sid, operation=OperationType.GENERATE)
        mock_orch.resolve = AsyncMock(return_value=ctx)
        request = ApplyRequest(session_id=sid)
        await _resolve_or_raise(request, _user(), _claims(), OperationType.APPLY)
        mock_authz.assert_called_once()
        self.assertEqual(mock_authz.call_args[0][1], ActionName.APPLY)
        self.assertEqual(mock_authz.call_args.kwargs["providers"], PROVIDERS)
        self.assertEqual(mock_authz.call_args.kwargs["repo_uri"], ctx.repo_uri)
        self.assertEqual(
            mock_authz.call_args.kwargs["root_module_path"], ctx.root_module_path
        )

    @patch("src.api.v1.terraform.authorize_providers", new_callable=AsyncMock)
    @patch("src.api.v1.terraform._workspace")
    @patch("src.api.v1.terraform._orchestration")
    @patch("src.api.v1.terraform.assert_session_access", new_callable=AsyncMock)
    async def test_iteration_uses_session_operation_as_action(
        self, mock_access, mock_orch, mock_ws, mock_authz
    ):
        mock_ws.validate_uri = AsyncMock()
        sid = uuid4()
        ctx = _session_ctx(sid)
        mock_orch.resolve = AsyncMock(return_value=ctx)
        request = GenerateRequest(
            session_id=sid,
            q="continue",
        )
        await _resolve_or_raise(request, _user(), _claims(), OperationType.GENERATE)
        mock_authz.assert_called_once()
        self.assertEqual(mock_authz.call_args[0][1], ActionName.GENERATE)

    @patch("src.api.v1.terraform.authorize_providers", new_callable=AsyncMock)
    @patch("src.api.v1.terraform._workspace")
    @patch("src.api.v1.terraform._orchestration")
    @patch("src.api.v1.terraform.assert_session_access", new_callable=AsyncMock)
    async def test_authz_deny_raises_403(
        self, mock_access, mock_orch, mock_ws, mock_authz
    ):
        mock_ws.validate_uri = AsyncMock()
        sid = uuid4()
        mock_orch.resolve = AsyncMock(
            return_value=_session_ctx(sid, operation=OperationType.GENERATE)
        )
        mock_authz.side_effect = HTTPException(status_code=403, detail="Denied")
        request = ApplyRequest(session_id=sid)
        with self.assertRaises(HTTPException) as cm:
            await _resolve_or_raise(request, _user(), _claims(), OperationType.APPLY)
        self.assertEqual(cm.exception.status_code, 403)


class TestFirstCallSetupAuthorizer(unittest.IsolatedAsyncioTestCase):
    """``_Inputs``: how a first call authorizes once its providers are known."""

    def test_of_carries_the_claims_action_and_answers(self):
        answers = ManifestAnswers(scopes={"azurerm": "sub-123"})
        claims = _claims()
        first = _Inputs.of(
            GenerateRequest(
                repo_uri="https://dev.azure.com/org/proj/_git/repo",
                q="x",
                manifest=answers,
            ),
            claims,
            OperationType.DRIFT,
        )
        self.assertTrue(first.first_call)
        self.assertIs(first.claims, claims)
        self.assertEqual(first.action, ActionName.DRIFT)
        self.assertEqual(first.answers, answers)

        iteration = _Inputs.of(
            GenerateRequest(session_id=uuid4(), q="x"), claims, OperationType.GENERATE
        )
        self.assertFalse(iteration.first_call)

    @patch("src.api.v1.terraform.authorize_providers", new_callable=AsyncMock)
    async def test_authorizer_checks_the_setup_pairs_on_the_session_module(
        self, mock_authz
    ):
        ctx = _session_ctx()
        claims = _claims()
        inputs = _Inputs(first_call=True, claims=claims, action=ActionName.IMPORT)
        pairs = (ProviderScope("google", "proj-1"),)

        await inputs.authorizer(ctx)(pairs)

        mock_authz.assert_awaited_once_with(
            claims,
            ActionName.IMPORT,
            providers=pairs,
            repo_uri=ctx.repo_uri,
            root_module_path=ctx.root_module_path,
        )

    @patch("src.api.v1.terraform.authorize_providers", new_callable=AsyncMock)
    async def test_authorizer_denial_becomes_a_session_error(self, mock_authz):
        mock_authz.side_effect = HTTPException(status_code=403, detail="Denied")
        inputs = _Inputs(first_call=True, claims=_claims(), action=ActionName.GENERATE)

        with self.assertRaises(ExceptionHandler) as cm:
            await inputs.authorizer(_session_ctx())(PROVIDERS)
        self.assertEqual(cm.exception.error_code, 403)
        self.assertIn("Denied", cm.exception.message)


class TestRunnerAuthorizesFirstCallSetup(unittest.IsolatedAsyncioTestCase):
    """``_make_runner`` hands the setup authorizer to first calls only."""

    def setUp(self):
        self.prepare = AsyncMock()
        self.db = AsyncMock()
        self.db.get_last_status.return_value = MagicMock(status=None)
        self.notify = AsyncMock()
        orchestration = MagicMock(acquire=AsyncMock(), release=AsyncMock())
        workspace = MagicMock(setup_call_dir=AsyncMock(return_value=Path("/w/c")))
        workspace.root_module_dir.return_value = Path("/w/c/infra")
        inputs_service = MagicMock(prepare=self.prepare)
        for target, value in (
            ("src.api.v1.terraform._orchestration", orchestration),
            ("src.api.v1.terraform._workspace", workspace),
            ("src.api.v1.terraform.tracer", MagicMock()),
            ("src.api.v1.terraform.LangfuseTracer", MagicMock()),
            ("src.api.v1.terraform.DatabaseService", self.db),
            (
                "src.api.v1.terraform.NotificationServiceClient",
                MagicMock(notify_exception_failure=self.notify),
            ),
            (
                "src.api.v1.terraform.ApplicationFactory.get_session_inputs_service",
                MagicMock(return_value=inputs_service),
            ),
        ):
            patcher = patch(target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.handled = AsyncMock()

    async def _run(self, inputs: _Inputs, ctx: SessionContext) -> None:
        async def build(_ctx):
            return self.handled

        await _make_runner(ctx, build, inputs)()

    @patch("src.api.v1.terraform.authorize_providers", new_callable=AsyncMock)
    async def test_first_call_setup_is_authorized_on_the_manifest_pairs(
        self, mock_authz
    ):
        ctx = _session_ctx(operation=OperationType.IMPORT)
        claims = _claims()
        await self._run(
            _Inputs(first_call=True, claims=claims, action=ActionName.IMPORT), ctx
        )

        self.prepare.assert_awaited_once()
        authorize = self.prepare.await_args.kwargs["authorize"]
        self.assertTrue(self.prepare.await_args.kwargs["first_call"])
        pairs = (ProviderScope("google", "proj-1"),)
        await authorize(pairs)
        mock_authz.assert_awaited_once_with(
            claims,
            ActionName.IMPORT,
            providers=pairs,
            repo_uri=ctx.repo_uri,
            root_module_path=ctx.root_module_path,
        )
        self.handled.assert_awaited_once()

    async def test_iteration_setup_is_not_authorized_again(self):
        await self._run(
            _Inputs(first_call=False, claims=_claims(), action=ActionName.GENERATE),
            _session_ctx(),
        )

        self.prepare.assert_awaited_once()
        self.assertIsNone(self.prepare.await_args.kwargs["authorize"])

    async def test_a_denied_setup_fails_the_session_without_running_it(self):
        ctx = _session_ctx()
        self.prepare.side_effect = ExceptionHandler("Denied", 403)

        await self._run(
            _Inputs(first_call=True, claims=_claims(), action=ActionName.GENERATE),
            ctx,
        )

        self.handled.assert_not_awaited()
        self.db.mark_failed.assert_awaited_once()
        self.assertIn("Denied", self.db.mark_failed.await_args.args[1])
        self.notify.assert_awaited_once()
