# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

# pyright: basic
import unittest
from uuid import uuid4

from unittest.mock import AsyncMock, MagicMock

from src.application.services.requests_filter_service import RequestsFilterService
from src.domains.entities.history import History
from src.domains.entities.session import SessionContext
from src.domains.value_objects import Conventions
from src.shared.constants import OperationType, PromptsLibrary, TerraformProvider


class TestRequestsFilterService(unittest.IsolatedAsyncioTestCase):
    def _build_ctx(self, operation: OperationType) -> SessionContext:
        return SessionContext(
            id=uuid4(),
            user_id="test-user",
            round_id=1,
            repo_uri="https://example.com/repo.git",
            scope_id="scope-1",
            terraform_prv=TerraformProvider.AZURE,
            branch_name="Nebula/test",
            iac_path="/iac",
            operation_type=operation,
            history=[],
        )

    def _build_service(self, ctx: SessionContext):
        llm_svc = AsyncMock()
        tool_svc = MagicMock()
        template_svc = AsyncMock()
        session_svc = MagicMock()

        tool_svc.get_available_tools.return_value = []
        tool_svc.get_sentinel_tool.return_value = MagicMock()

        response = MagicMock()
        response.result = {"status": True, "explanation": "ok"}
        llm_svc.generate.return_value = response

        svc = RequestsFilterService(
            second_llm_service=llm_svc,
            tool_service=tool_svc,
            template_service=template_svc,
            session_service=session_svc,
            session_ctx=ctx,
        )
        return svc, template_svc

    async def _assert_filter_renders_with_operation(self, operation: OperationType):
        ctx = self._build_ctx(operation)
        svc, template_svc = self._build_service(ctx)
        conventions = Conventions(templates=["storage_account"], abbreviations=["sta-"])
        history = History([])

        status, rationale = await svc.filter("some request", history, conventions)

        self.assertTrue(status)
        self.assertEqual(rationale, "ok")
        template_svc.render.assert_awaited_once()
        call_kwargs = template_svc.render.call_args.kwargs
        self.assertEqual(call_kwargs["prompt"], PromptsLibrary.REQUESTS_FILTER)
        self.assertEqual(call_kwargs["operation_type"], operation)
        self.assertEqual(call_kwargs["resources"], ["storage_account"])
        self.assertEqual(call_kwargs["abbreviations"], ["sta-"])
        self.assertTrue(call_kwargs["include_forbidden_actions"])

    async def test_filter_renders_with_drift_operation(self):
        await self._assert_filter_renders_with_operation(OperationType.DRIFT)

    async def test_filter_renders_with_generate_operation(self):
        await self._assert_filter_renders_with_operation(OperationType.GENERATE)


if __name__ == "__main__":
    unittest.main()
