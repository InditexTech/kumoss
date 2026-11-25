# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import unittest

from unittest.mock import AsyncMock, MagicMock

from src.application.exceptions import RequestFilterException
from src.application.services.requests_filter_service import RequestsFilterService
from src.domains.entities.history import History
from src.shared.constants import OperationType, PromptsLibrary


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
    """filter() records the rejection in the history and raises.

    Persisting the round (``save()``) and marking the session UNCOMPLETED are
    left to the handlers' ``finally`` and the API runner respectively.
    """

    def _build_service(self, status: bool, explanation: str):
        llm_svc = AsyncMock()
        tool_svc = MagicMock()
        template_svc = AsyncMock()
        session_svc = AsyncMock()

        tool_svc.get_available_tools.return_value = []
        tool_svc.get_sentinel_tool.return_value = MagicMock()

        response = MagicMock()
        response.result = {"status": status, "explanation": explanation}
        llm_svc.generate.return_value = response

        svc = RequestsFilterService(
            second_llm_service=llm_svc,
            tool_service=tool_svc,
            template_service=template_svc,
            session_service=session_svc,
        )
        return svc, session_svc

    async def test_rejection_appends_turn_and_raises(self):
        svc, _ = self._build_service(False, "Not a valid IaC request.")
        history = History([])

        with self.assertRaises(RequestFilterException) as raised:
            await svc.filter(
                "What is the capital of France?", history, OperationType.GENERATE
            )

        self.assertEqual(raised.exception.message, "Not a valid IaC request.")
        self.assertEqual(raised.exception.error_code, 400)
        self.assertEqual(len(history), 1)
        turn = history.get_last_turn()
        self.assertEqual(str(turn.user), "What is the capital of France?")
        self.assertEqual(str(turn.assistant), "Not a valid IaC request.")

    async def test_rejection_leaves_session_bookkeeping_to_the_caller(self):
        svc, session_svc = self._build_service(False, "Not a valid IaC request.")

        with self.assertRaises(RequestFilterException):
            await svc.filter("off-topic", History([]), OperationType.GENERATE)

        session_svc.save.assert_not_awaited()
        session_svc.update_status.assert_not_awaited()

    async def test_accepted_request_has_no_side_effects(self):
        svc, session_svc = self._build_service(True, "Looks good.")
        history = History([])

        await svc.filter("add a vnet", history, OperationType.GENERATE)

        self.assertEqual(len(history), 0)
        session_svc.save.assert_not_awaited()
        session_svc.update_status.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
