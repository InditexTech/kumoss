# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

# pyright: basic
"""The compliance check: the policy and the intent check, one report.

The intent check reads the plan against every request of the session,
including the one whose round produced the plan."""

import json
import unittest
from types import SimpleNamespace
from typing import Literal, cast
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from src.domains.dto import (
    ComplianceCheckReport,
    ComplianceViolation,
    IntentCheck,
    PolicyDecision,
    ToolResultDTO,
)
from src.domains.entities import SessionContext
from src.domains.exceptions import PolicyEvaluationError
from src.domains.services.compliance_check_service import ComplianceCheckService
from src.domains.value_objects import ProviderScope
from src.shared.config import system_config
from src.shared.constants import OperationType

PLAN_JSON = {"format_version": "1.2", "resource_changes": []}


def _violation(
    rule_id: str,
    severity: Literal["info", "warning", "error", "critical"],
    source: Literal["intent", "opa"] = "intent",
) -> ComplianceViolation:
    return ComplianceViolation(
        rule_id=rule_id,
        severity=severity,
        resource="a.b",
        message=f"{rule_id} broken",
        source=source,
    )


def _intent(
    *violations: ComplianceViolation, summary: str = "Plan is fine."
) -> IntentCheck:
    return IntentCheck(
        violations=list(violations),
        summary=summary,
        checked_rules=["scope_exceeded", "scope_incomplete"],
    )


def _deletion() -> ComplianceViolation:
    return _violation("critical_deletion", "critical", source="opa")


def _clean_policy() -> AsyncMock:
    engine = AsyncMock()
    engine.evaluate.return_value = PolicyDecision(
        violations=[], checked_rules=["critical_deletion"], revisions=["v1"]
    )
    return engine


class TestComplianceQuery(unittest.IsolatedAsyncioTestCase):
    async def test_every_user_query_reaches_the_intent_check(self):
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
            name="report_intent_findings",
            tool_call_id="call_1",
            success=True,
            result=IntentCheck(violations=[], summary="ok", checked_rules=[]),
            error_message=None,
        )
        svc = ComplianceCheckService(
            tool_service=MagicMock(),
            llm_service=llm,
            template_service=AsyncMock(),
            artifact_service=AsyncMock(),
            policy_engine=_clean_policy(),
        )

        with patch(
            "src.domains.services.compliance_check_service.system_config"
        ) as config:
            config.orchestration.enable_compliance_checker = True
            _ = await svc.check(ctx, "<plan>", PLAN_JSON)

        query = cast(str, llm.generate.await_args.kwargs["query"])
        self.assertEqual(
            query,
            "The user requests:\n- add a vnet\n- and a subnet\n\n"
            "The Terraform plan to check:\n<plan>",
        )


class TestComplianceReportMerge(unittest.TestCase):
    def test_a_policy_deny_fails_a_passing_intent_check_and_leads_the_summary(self):
        policy = PolicyDecision(
            violations=[_deletion()],
            checked_rules=["critical_deletion"],
            revisions=["v7"],
        )

        report = ComplianceCheckReport.merge(_intent(), policy)

        self.assertFalse(report.passed)
        self.assertEqual(
            report.summary,
            "Blocked by the compliance policy: 1 finding (critical_deletion). "
            + "Plan is fine.",
        )
        self.assertEqual(report.violations[0].source, "opa")
        self.assertEqual(
            report.checked_rules,
            ["critical_deletion", "scope_exceeded", "scope_incomplete"],
        )
        self.assertEqual(report.policy_revisions, ["v7"])

    def test_policy_warnings_do_not_fail_the_report(self):
        policy = PolicyDecision(
            violations=[_violation("public_ip", "warning", source="opa")],
            checked_rules=["public_ip"],
            revisions=["v7"],
        )

        report = ComplianceCheckReport.merge(_intent(), policy)

        self.assertTrue(report.passed)
        self.assertEqual(report.summary, "Plan is fine.")
        self.assertEqual(len(report.violations), 1)

    def test_a_failing_intent_check_stays_failed_with_a_clean_policy(self):
        intent = _intent(_violation("scope_exceeded", "error"), summary="Too much.")
        policy = PolicyDecision(violations=[], checked_rules=["x"], revisions=[])

        report = ComplianceCheckReport.merge(intent, policy)

        self.assertFalse(report.passed)
        self.assertEqual(report.summary, "Too much.")

    def test_reports_stored_before_the_policy_engine_still_load(self):
        stored = json.dumps(
            {
                "passed": False,
                "violations": [
                    {
                        "rule_id": "critical_deletion",
                        "severity": "critical",
                        "resource": "a.b",
                        "message": "deleted",
                        "suggested_fix": None,
                    }
                ],
                "summary": "s",
                "checked_rules": ["critical_deletion"],
            }
        )

        report = ComplianceCheckReport.model_validate_json(stored)

        self.assertEqual(report.violations[0].source, "intent")
        self.assertEqual(report.policy_revisions, [])

    def test_findings_stored_with_the_llm_source_load_as_intent(self):
        stored = json.dumps(
            {
                "passed": False,
                "violations": [
                    {
                        "rule_id": "scope_exceeded",
                        "severity": "error",
                        "message": "unrequested",
                        "source": "llm",
                    }
                ],
                "summary": "s",
                "checked_rules": ["scope_exceeded"],
            }
        )

        report = ComplianceCheckReport.model_validate_json(stored)

        self.assertEqual(report.violations[0].source, "intent")

    def test_a_report_with_a_single_policy_revision_still_loads(self):
        stored = json.dumps(
            {
                "passed": True,
                "violations": [],
                "summary": "s",
                "checked_rules": ["critical_deletion"],
                "policy_revision": "general/policies/compliance@3",
            }
        )

        report = ComplianceCheckReport.model_validate_json(stored)

        self.assertEqual(report.policy_revisions, ["general/policies/compliance@3"])
        self.assertNotIn("policy_revision", report.model_dump())


class TestComplianceCheckService(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        patcher = patch.object(
            system_config.orchestration, "enable_compliance_checker", True
        )
        patcher.start()
        self.addCleanup(patcher.stop)

        self.llm = AsyncMock()
        self.llm.generate.return_value = SimpleNamespace(result=_intent())
        self.artifacts = AsyncMock()
        self.engine = _clean_policy()
        self.service = ComplianceCheckService(
            tool_service=MagicMock(),
            llm_service=self.llm,
            template_service=AsyncMock(),
            artifact_service=self.artifacts,
            policy_engine=self.engine,
        )
        self.ctx = MagicMock()
        self.ctx.provider_types = ("azurerm",)
        self.ctx.history.user_queries = ["create a bucket"]

    async def _check(self, plan_json=PLAN_JSON) -> ComplianceCheckReport:
        return await self.service.check(
            ctx=self.ctx,
            plan="plan text",
            plan_json=plan_json,
        )

    def _stored(self) -> ComplianceCheckReport:
        self.artifacts.store_compliance_check.assert_awaited_once()
        kwargs = self.artifacts.store_compliance_check.await_args.kwargs
        return ComplianceCheckReport.model_validate_json(kwargs["content"])

    async def test_the_policy_evaluates_the_plan_json_for_the_providers(self):
        report = await self._check()

        self.engine.evaluate.assert_awaited_once_with(PLAN_JSON, ("azurerm",))
        self.assertTrue(report.passed)
        self.assertEqual(report.policy_revisions, ["v1"])
        self.assertIn("critical_deletion", report.checked_rules)

    async def test_a_deny_fails_the_check_and_one_merged_report_is_stored(self):
        self.engine.evaluate.return_value = PolicyDecision(
            violations=[_deletion()],
            checked_rules=["critical_deletion"],
            revisions=["v1"],
        )

        report = await self._check()

        self.assertFalse(report.passed)
        self.assertEqual(self._stored(), report)
        kwargs = self.artifacts.store_compliance_check.await_args.kwargs
        self.assertFalse(kwargs["passed"])

    async def test_an_engine_failure_blocks_and_the_intent_check_still_runs(self):
        self.engine.evaluate.side_effect = PolicyEvaluationError(
            message="opa eval timed out after 30s", error_code=504
        )

        report = await self._check()

        self.assertFalse(report.passed)
        [unavailable] = [v for v in report.violations if v.source == "opa"]
        self.assertEqual(unavailable.rule_id, "policy_unavailable")
        self.assertEqual(unavailable.severity, "error")
        self.assertIn("timed out", unavailable.message)
        self.assertEqual(report.policy_revisions, [])
        self.llm.generate.assert_awaited_once()
        self.assertEqual(self._stored(), report)

    async def test_a_missing_plan_json_blocks_without_calling_the_engine(self):
        report = await self._check(plan_json=None)

        self.engine.evaluate.assert_not_awaited()
        self.assertFalse(report.passed)
        self.assertEqual(report.violations[0].rule_id, "policy_unavailable")
        self.assertIn("JSON could not be read", report.violations[0].message)

    async def test_the_toggle_off_skips_both_checks(self):
        with patch.object(
            system_config.orchestration, "enable_compliance_checker", False
        ):
            report = await self._check()

        self.assertEqual(report, ComplianceCheckReport.empty())
        self.engine.evaluate.assert_not_awaited()
        self.llm.generate.assert_not_awaited()
        self.artifacts.store_compliance_check.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
