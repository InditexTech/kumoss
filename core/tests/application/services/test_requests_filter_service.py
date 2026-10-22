# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import unittest

from unittest.mock import AsyncMock, MagicMock

from src.application.services.requests_filter_service import RequestsFilterService
from src.domains.entities.history import History
from src.shared.constants import OperationType, PromptsLibrary, SessionStatus


class TestRequestsFilterService(unittest.IsolatedAsyncioTestCase):
    def _build_service(self):
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
        )
        return svc, template_svc

    async def test_filter_passes_drift_operation_type(self):
        svc, template_svc = self._build_service()
        history = History([])

        _ = await svc.filter("resolve the drift", history, OperationType.DRIFT)

        template_svc.render.assert_awaited_once_with(
            prompt=PromptsLibrary.REQUESTS_FILTER,
            operation_type=OperationType.DRIFT,
        )

    async def test_filter_passes_generate_operation_type(self):
        svc, template_svc = self._build_service()
        history = History([])

        _ = await svc.filter(
            "create a storage account", history, OperationType.GENERATE
        )

        template_svc.render.assert_awaited_once_with(
            prompt=PromptsLibrary.REQUESTS_FILTER,
            operation_type=OperationType.GENERATE,
        )


class TestRequestsFilterRejection(unittest.IsolatedAsyncioTestCase):
    """Rejection side-effects are centralised in filter(), not the handlers."""

    def _build_rejected_service(self):
        llm_svc = AsyncMock()
        tool_svc = MagicMock()
        template_svc = AsyncMock()
        session_svc = AsyncMock()

        tool_svc.get_available_tools.return_value = []
        tool_svc.get_sentinel_tool.return_value = MagicMock()

        response = MagicMock()
        response.result = {"status": False, "explanation": "Not a valid IaC request."}
        llm_svc.generate.return_value = response

        svc = RequestsFilterService(
            second_llm_service=llm_svc,
            tool_service=tool_svc,
            template_service=template_svc,
            session_service=session_svc,
        )
        return svc, session_svc

    async def test_rejection_appends_turn_and_persists_before_uncompleted(self):
        svc, session_svc = self._build_rejected_service()
        history = History([])

        ok = await svc.filter(
            "What is the capital of France?", history, OperationType.GENERATE
        )

        self.assertFalse(ok)
        self.assertEqual(len(history), 1)
        turn = history.get_last_turn()
        self.assertEqual(str(turn.user), "What is the capital of France?")
        self.assertEqual(str(turn.assistant), "Not a valid IaC request.")
        session_svc.save.assert_awaited_once_with("What is the capital of France?")
        session_svc.update_status.assert_awaited_once_with(
            msg="Not a valid IaC request.",
            status=SessionStatus.UNCOMPLETED,
        )

    async def test_save_is_called_before_update_status(self):
        svc, session_svc = self._build_rejected_service()
        call_order = []
        session_svc.save.side_effect = lambda *a, **kw: call_order.append("save")
        session_svc.update_status.side_effect = lambda *a, **kw: call_order.append(
            f"status:{kw.get('status')}"
        )

        await svc.filter("off-topic", History([]), OperationType.GENERATE)

        save_idx = call_order.index("save")
        status_idx = call_order.index(f"status:{SessionStatus.UNCOMPLETED}")
        self.assertLess(save_idx, status_idx)

    async def test_accepted_request_has_no_side_effects(self):
        llm_svc = AsyncMock()
        tool_svc = MagicMock()
        template_svc = AsyncMock()
        session_svc = AsyncMock()

        tool_svc.get_available_tools.return_value = []
        tool_svc.get_sentinel_tool.return_value = MagicMock()

        response = MagicMock()
        response.result = {"status": True, "explanation": "Looks good."}
        llm_svc.generate.return_value = response

        svc = RequestsFilterService(
            second_llm_service=llm_svc,
            tool_service=tool_svc,
            template_service=template_svc,
            session_service=session_svc,
        )
        history = History([])

        ok = await svc.filter("add a vnet", history, OperationType.GENERATE)

        self.assertTrue(ok)
        self.assertEqual(len(history), 0)
        session_svc.save.assert_not_awaited()
        session_svc.update_status.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
