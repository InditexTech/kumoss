# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import json
from collections.abc import Coroutine
from dataclasses import asdict
from typing import Callable, Any, cast

from src.application.exceptions import TerraformValidationFailedError
from src.application.services.requests_filter_service import RequestsFilterService
from src.application.services.report_service import ReportService
from src.application.services.terraform_drift_service import TerraformDriftService
from src.application.services.terraform_import_service import TerraformImportService
from src.domains.dto import (
    TerraformImportDTO,
    TerraformPlanDTO,
    ToolResultDTO,
)
from src.domains.entities import History
from src.domains.entities.session import SessionContext
from src.domains.interfaces import ITerraform
from src.domains.services import (
    SessionService,
    TemplateOrchestrationService,
    TerraformImportAddressService,
    TerraformTargetService,
    TerraformValidationService,
)
from src.domains.services.llm_service import LLMOrchestrationService
from src.domains.services.tool_service import ToolOrchestrationService
from src.shared.config import system_config
from src.shared.constants import (
    OperationType,
    PromptsLibrary,
    ReportType,
    SessionStatus,
    ToolContext,
)
from src.shared.logger import logging


class TerraformImportHandler:
    def __init__(
        self,
        session_ctx: SessionContext,
        session_service: SessionService,
        terraform_service: ITerraform,
        validation_service: TerraformValidationService,
        template_service: TemplateOrchestrationService,
        requests_filter_service: RequestsFilterService,
        import_service: TerraformImportService,
        import_address_service: TerraformImportAddressService,
        target_service: TerraformTargetService,
        drift_service: TerraformDriftService,
        report_service: ReportService,
        llm_service: LLMOrchestrationService,
        tool_service: ToolOrchestrationService,
    ):
        self.__terraform_svc = terraform_service
        self.__validation_svc = validation_service
        self.__session_svc = session_service
        self.__template_svc = template_service
        self.__report_svc = report_service
        self.__requests_filter_svc = requests_filter_service
        self.__import_svc = import_service
        self.__import_address_svc = import_address_service
        self.__target_svc = target_service
        self.__drift_svc = drift_service
        self.__llm_svc = llm_service
        self.__tool_svc = tool_service
        self.__ctx = session_ctx

    async def __report_nothing_to_import(self, q: str, msg: str) -> None:
        """Close a round that found nothing to import with an empty report.

        The scope could not be listed, holds nothing importable or is
        already fully managed, or the request targets nothing unmanaged —
        ``msg`` says which. Reporting instead of dead-ending leaves the session
        completed: the runner marks any handler that returns without setting
        UNCOMPLETED as completed.
        """
        ctx = self.__ctx
        ctx.history.append_turn(q, msg)
        _ = await self.__report_svc.generate_report(
            ctx=ctx,
            type=ReportType.IMPORT,
            content=json.dumps(
                {
                    "selected_resource_ids": [],
                    "import_results": asdict(
                        TerraformImportDTO(imported=[], failed=[])
                    ),
                    "summary": msg,
                }
            ),
        )

    async def handle(
        self, q: str, is_partial: bool
    ) -> Callable[[], Coroutine[Any, Any, None]]:
        ctx = self.__ctx

        async def background_task():
            try:
                await self.__session_svc.next_round(q)
                _ = await self.__session_svc.update_status(
                    msg=q,
                    prompt=await self.__template_svc.render(
                        PromptsLibrary.STATUS_UPDATE
                    ),
                    status=SessionStatus.FILTERING,
                    history=ctx.history,
                )
                if is_partial:
                    ok, rationale = await self.__requests_filter_svc.filter(
                        q, ctx.history, ctx.operation
                    )
                    if not ok:
                        ctx.history.append_turn(q, rationale)
                        _ = await self.__session_svc.update_status(
                            msg=rationale,
                            status=SessionStatus.UNCOMPLETED,
                        )
                        return

                conventions = await self.__template_svc.compose_template(q, ctx.history)

                discovery = await self.__import_svc.get_unmanaged_resources(
                    scope_id=ctx.scope_id,
                    terraform_provider=ctx.terraform_prv,
                )
                unmanaged_ids = discovery.resource_ids
                if not unmanaged_ids:
                    await self.__report_nothing_to_import(q, discovery.feedback)
                    return

                selected_ids: list[str] = unmanaged_ids
                if is_partial:
                    filter_result: ToolResultDTO = await self.__llm_svc.generate(
                        query=q,
                        tools=[
                            self.__tool_svc.get_sentinel_tool(
                                context=ToolContext.TASK_SPLITTER,
                            )
                        ],
                        prompt=await self.__template_svc.render(
                            prompt=PromptsLibrary.IMPORT_FILTER,
                            unmanaged_ids=unmanaged_ids,
                            resources=conventions.templates,
                            abbreviations=conventions.abbreviations,
                        ),
                        history=ctx.history,
                    )
                    selected_ids = cast(list[str], filter_result.result["operations"])

                    if not selected_ids:
                        filter_explanation: str = (
                            cast(str, filter_result.result.get("explanation", ""))
                            or "No unmanaged resource matched the request."
                        )
                        await self.__report_nothing_to_import(q, msg=filter_explanation)
                        return

                async def plan_callback(
                    local_history: History,
                ) -> TerraformPlanDTO:
                    return await self.__terraform_svc.plan(
                        targets=await self.__target_svc.generate_session(local_history),
                    )

                q_import = (
                    f"{q}\n\nCreate a Terraform resource block for each of these "
                    + "\n".join(f"- {rid}" for rid in selected_ids)
                )
                plan_result = await self.__validation_svc.generate_and_validate(
                    q=q_import,
                    ctx=ctx,
                    conventions=conventions,
                    include_forbidden_actions=False,
                    operation_type=OperationType.IMPORT,
                    validator=plan_callback,
                )

                if not plan_result.ok:
                    fail_msg = await self.__report_svc.summarize_problem(
                        feedback=plan_result.feedback,
                        history=ctx.history,
                    )
                    raise TerraformValidationFailedError(
                        message=fail_msg,
                        error_code=500,
                    )

                imports = await self.__import_address_svc.get_import_addresses(
                    ctx.history, selected_ids
                )
                if not imports:
                    logging.warning(
                        "There is nothing to import: no generated resource block "
                        + f"was found in the branch diff for selected ids {selected_ids}"
                    )
                import_results = await self.__import_svc.import_resources(imports)
                if import_results.failed:
                    logging.warning(
                        f"{len(import_results.failed)}/{len(imports)} imports failed"
                    )

                imported_addresses = import_results.addresses
                # The report is fed the plan text, not the ref: the ref is
                # what the drift read consumes, and only the convergence
                # round that follows the imports sees state as it now is.
                plan_after_import = plan_result.stdout
                if imported_addresses:
                    drift = await self.__drift_svc.detect_and_resolve_drift(
                        plan=plan_result.plan,
                        filter_session_changes=False,
                        targets=imported_addresses,
                        conventions=conventions,
                        max_iterations=system_config.orchestration.max_drift_reports,
                    )
                    # Only a failed read aborts the round: drift the loop
                    # could not reconcile is an outcome to report, not a
                    # fault, and it is ``feedback`` that tells them apart.
                    if drift.feedback:
                        fail_msg = await self.__report_svc.summarize_problem(
                            feedback=drift.feedback,
                            history=ctx.history,
                        )
                        raise TerraformValidationFailedError(
                            message=fail_msg,
                            error_code=500,
                        )

                    plan_after_import = drift.stdout or plan_after_import

                _ = await self.__report_svc.generate_report(
                    ctx=ctx,
                    type=ReportType.IMPORT,
                    content=json.dumps(
                        {
                            "selected_resource_ids": selected_ids,
                            "import_results": asdict(import_results),
                            "plan_after_import": plan_after_import,
                        }
                    ),
                )
            finally:
                await self.__session_svc.save()

        return background_task
