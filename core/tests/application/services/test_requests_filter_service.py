# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import unittest

from unittest.mock import AsyncMock, MagicMock

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


if __name__ == "__main__":
    unittest.main()
