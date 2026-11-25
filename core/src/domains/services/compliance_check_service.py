# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from typing import Any

from src.domains.dto import (
    ComplianceCheckReport,
    ComplianceViolation,
    PolicyDecision,
    ToolResultDTO,
)
from src.domains.entities import SessionContext
from src.domains.exceptions import PolicyEvaluationError
from src.domains.interfaces import IPolicyEngine
from src.domains.services.artifact_storage_service import ArtifactStorageService
from src.domains.services.llm_service import LLMOrchestrationService
from src.domains.services.template_service import TemplateOrchestrationService
from src.domains.services.tool_service import ToolOrchestrationService
from src.domains.value_objects import Conventions
from src.shared.config import system_config
from src.shared.constants import ContentType, PromptsLibrary, ToolContext
from src.shared.logger import logging


class ComplianceCheckService:
    """Audits a generate round's final plan twice: deterministically with
    the policy engine, then with the LLM against the conventions. Both run
    under ``enable_compliance_checker`` and end up in one report."""

    # The finding that stands in for a policy that could not be evaluated.
    POLICY_UNAVAILABLE_RULE: str = "policy_unavailable"

    def __init__(
        self,
        tool_service: ToolOrchestrationService,
        llm_service: LLMOrchestrationService,
        template_service: TemplateOrchestrationService,
        artifact_service: ArtifactStorageService,
        policy_engine: IPolicyEngine,
    ):
        self.__tool_svc = tool_service
        self.__llm_svc = llm_service
        self.__template_svc = template_service
        self.__artifact_svc = artifact_service
        self.__policy_engine = policy_engine

    async def check(
        self,
        ctx: SessionContext,
        conventions: Conventions,
        plan: str,
        plan_json: dict[str, Any] | None,
    ) -> ComplianceCheckReport:
        """``plan`` is the plan text the LLM audits; ``plan_json`` the same
        plan's ``show -json``, which the policy evaluates (None when it
        could not be read, which blocks like any policy failure)."""
        if not system_config.orchestration.enable_compliance_checker:
            return ComplianceCheckReport.empty()

        policy = await self.__evaluate_policy(ctx, plan_json)

        requests = "\n".join(f"- {q}" for q in ctx.history.user_queries)
        query = (
            f"The user requests:\n{requests}\n\nThe Terraform plan to audit:\n{plan}"
        )

        result: ToolResultDTO = await self.__llm_svc.generate(
            query=query,
            tools=self.__tool_svc.get_available_tools(
                contexts=[ToolContext.COMPLIANCE_CHECK]
            ),
            prompt=await self.__template_svc.render(
                PromptsLibrary.COMPLIANCE_CHECKER,
                resources=conventions.templates,
                abbreviations=conventions.abbreviations,
            ),
        )

        report = ComplianceCheckReport.merge(result.result, policy)
        _ = await self.__artifact_svc.store_compliance_check(
            session_id=ctx.id,
            round_id=ctx.round_id,
            passed=report.passed,
            content=report.model_dump_json(),
            content_type=ContentType.JSON,
        )
        return report

    async def __evaluate_policy(
        self, ctx: SessionContext, plan_json: dict[str, Any] | None
    ) -> PolicyDecision:
        """The policy's decision, or a blocking ``policy_unavailable``
        finding when there is none: a policy that cannot run fails closed."""
        if plan_json is None:
            return self.__unavailable("the plan's JSON could not be read")
        try:
            return await self.__policy_engine.evaluate(plan_json, ctx.provider_types)
        except PolicyEvaluationError as e:
            return self.__unavailable(e.message)

    def __unavailable(self, reason: str) -> PolicyDecision:
        logging.error(f"Compliance policy could not be evaluated: {reason}")
        return PolicyDecision(
            violations=[
                ComplianceViolation(
                    rule_id=self.POLICY_UNAVAILABLE_RULE,
                    severity="error",
                    message=(
                        "The compliance policy could not be evaluated, so the "
                        + f"plan is blocked until it can: {reason}"
                    ),
                    source="opa",
                )
            ],
            checked_rules=[],
            revision=None,
        )
