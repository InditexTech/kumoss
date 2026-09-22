# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Which tools each report type is given.

A drift report is written from the branch's own changes, so it needs the
workspace inspection set — `diff_history` above all. The plan and apply
reports are handed the output they describe and only need `web_search`.
"""

import unittest
from unittest.mock import AsyncMock, MagicMock

from src.application.services.report_service import ReportService
from src.shared.constants import ReportType, ToolContext


def _tools(context: ToolContext) -> list[str]:
    return [f"{context.value}-{i}" for i in range(3)]


class TestReportServiceToolSelection(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.llm_svc = AsyncMock()
        self.llm_svc.generate.return_value = MagicMock(success=True)
        self.tool_svc = MagicMock()
        self.tool_svc.get_available_tools.side_effect = _tools
        self.template_svc = AsyncMock()
        self.session_svc = AsyncMock()
        self.artifact_svc = AsyncMock()
        self.svc = ReportService(
            second_llm_service=self.llm_svc,
            tool_service=self.tool_svc,
            template_service=self.template_svc,
            session_service=self.session_svc,
            artifact_service=self.artifact_svc,
        )

    async def _tools_used(self, type: ReportType) -> list[str]:
        _ = await self.svc.generate_report(
            ctx=MagicMock(), type=type, content="content"
        )
        return self.llm_svc.generate.await_args.kwargs["tools"]

    async def test_drift_reports_inspect_the_workspace(self):
        tools = await self._tools_used(ReportType.DRIFT)

        # A coroutine here would reach the provider as an invalid tool list.
        self.assertIsInstance(tools, list)
        self.assertEqual(tools, _tools(ToolContext.WORKSPACE_INSPECTION))

    async def test_plan_reports_search_the_web(self):
        tools = await self._tools_used(ReportType.GENERATE)

        self.assertEqual(tools, _tools(ToolContext.EXTERNAL_INFORMATION))

    async def test_apply_reports_search_the_web(self):
        tools = await self._tools_used(ReportType.APPLY)

        self.assertEqual(tools, _tools(ToolContext.EXTERNAL_INFORMATION))


if __name__ == "__main__":
    unittest.main()
