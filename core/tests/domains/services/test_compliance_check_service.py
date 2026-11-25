# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""The compliance checker audits the plan against every request of the
session, including the one whose round produced the plan."""

import unittest
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from src.domains.dto import ComplianceCheckReport, ToolResultDTO
from src.domains.entities import SessionContext
from src.domains.services.compliance_check_service import ComplianceCheckService
from src.domains.value_objects import Conventions, ProviderScope
from src.shared.constants import OperationType


class TestComplianceQuery(unittest.IsolatedAsyncioTestCase):
    async def test_every_user_query_reaches_the_audit(self):
        ctx = SessionContext(
            id=uuid4(),
            user_id="user@example.com",
            round_id=2,
            repo_uri="https://example.com/foo.git",
            providers=(ProviderScope("azurerm", "sub-123"),),
            branch_name="Kumoss/x",
            root_module_path="infra",
            operation_type=OperationType.GENERATE,
            history=[],
            chat_history=[{"user": "add a vnet", "assistant": "Done."}],
            user_queries=["add a vnet", "and a subnet"],
        )
        llm = AsyncMock()
        llm.generate.return_value = ToolResultDTO(
            name="report_compliance_findings",
            tool_call_id="call_1",
            success=True,
            result=ComplianceCheckReport(
                passed=True, violations=[], summary="ok", checked_rules=[]
            ),
            error_message=None,
        )
        svc = ComplianceCheckService(
            tool_service=MagicMock(),
            llm_service=llm,
            template_service=AsyncMock(),
            artifact_service=AsyncMock(),
        )

        with patch(
            "src.domains.services.compliance_check_service.system_config"
        ) as config:
            config.orchestration.enable_compliance_checker = True
            _ = await svc.check(ctx, Conventions.empty(), "<plan>")

        query = cast(str, llm.generate.await_args.kwargs["query"])
        self.assertEqual(
            query,
            "The user requests:\n- add a vnet\n- and a subnet\n\n"
            "The Terraform plan to audit:\n<plan>",
        )
