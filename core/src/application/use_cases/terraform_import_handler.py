# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import json
from collections.abc import Coroutine
from dataclasses import asdict
from typing import Callable, Any, cast

from src.application.exceptions import SetLockError, TerraformValidationFailedError
from src.application.services.requests_filter_service import RequestsFilterService
from src.application.services.report_service import ReportService
from src.application.services.terraform_drift_service import TerraformDriftService
from src.application.services.terraform_import_service import TerraformImportService
from src.domains.dto import TerraformImportDTO, TerraformValidationDTO, ToolResultDTO
from src.domains.entities import History
from src.domains.entities.session import SessionContext
from src.domains.interfaces import ITerraform
from src.domains.services import (
    ComplianceCheckService,
    SessionService,
    TemplateOrchestrationService,
    TerraformImportAddressService,
    TerraformTargetService,
    TerraformValidationService,
)
from src.domains.services.database_service import DatabaseService
from src.domains.services.llm_service import LLMOrchestrationService
from src.domains.services.tool_service import ToolOrchestrationService
from src.infrastructure.external.notification_service import NotificationServiceClient
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
        compliance_service: ComplianceCheckService,
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
        self.__compliance_svc = compliance_service
        self.__llm_svc = llm_service
        self.__tool_svc = tool_service
        self.__ctx = session_ctx

    async def __report_nothing_to_import(self, q: str, msg: str) -> None:
        """Close a round that found nothing to import with an empty report.

        The scope is already fully managed, or the request targets nothing
        unmanaged. Reporting instead of dead-ending leaves the session
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

                # Step 1 — Discovery
                unmanaged_ids = await self.__import_svc.get_unmanaged_resources(
                    scope_id=ctx.scope_id,
                    terraform_provider=ctx.terraform_prv,
                )
                if not unmanaged_ids:
                    await self.__report_nothing_to_import(
                        q, "No unmanaged resources found in scope."
                    )
                    return

                # Step 2 — Selection (import_filter agent), only for a partial
                # round. A full round imports the whole scope diff, so every
                # unmanaged id is selected without asking the agent to narrow
                # it down. The task splitter sentinel is the generic "report a
                # list of strings" tool: here each operation is a selected
                # resource id.
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
                    # `explanation` is optional on the task splitter tool.
                    filter_explanation: str = (
                        cast(str, filter_result.result.get("explanation", ""))
                        or "No unmanaged resource matched the request."
                    )

                    if not selected_ids:
                        await self.__report_nothing_to_import(q, filter_explanation)
                        return

                # Step 3 — Config generation (iac_generator prompt, import mode)
                async def validation_callback(
                    local_history: History,
                ) -> TerraformValidationDTO:
                    return await self.__terraform_svc.validate(
                        targets=await self.__target_svc.generate_session(local_history),
                        get_drift=False,
                    )

                validation = await self.__validation_svc.generate_and_validate(
                    q=q,
                    ctx=ctx,
                    conventions=conventions,
                    include_forbidden_actions=False,
                    operation_type=OperationType.IMPORT,
                    validator=validation_callback,
                    selected_ids=selected_ids,
                )

                if not validation.validation:
                    fail_msg = await self.__report_svc.summarize_problem(
                        feedback=validation.feedback,
                        history=ctx.history,
                    )
                    raise TerraformValidationFailedError(
                        message=fail_msg,
                        error_code=500,
                    )

                # Step 4 — Import execution. The generated blocks are already
                # committed, so the branch diff is the source of truth for which
                # addresses exist; the selected ids say what each is imported
                # from, since a block never carries its own cloud resource id.
                imports = await self.__import_address_svc.get_import_addresses(
                    ctx.history, selected_ids
                )
                if not imports:
                    logging.warning(
                        f"There is nothing to import: no generated resource block "
                        f"was found in the branch diff for selected ids {selected_ids}"
                    )
                import_results = await self.__import_svc.import_resources(imports)
                if import_results.failed:
                    logging.warning(
                        f"{len(import_results.failed)}/{len(imports)} imports failed"
                    )

                # Step 5 — Convergence: the imported state now mirrors the real
                # resources, but the generated blocks hold guessed arguments.
                # Reuse the drift resolution loop so the LLM rewrites the code
                # until a plan over the imported addresses reports no changes.
                imported_addresses = import_results.addresses
                plan_after_import = validation.terraform_plan
                if imported_addresses:
                    # The drift service plans over the given targets with its
                    # own terraform service; the session changes filter stays
                    # off because every imported address must converge, not
                    # just the ones this round touched.
                    convergence = await self.__drift_svc.detect_and_resolve_drift(
                        filter_session_changes=False,
                        targets=imported_addresses,
                        conventions=conventions,
                        max_iterations=system_config.orchestration.max_drift_reports,
                    )
                    if not convergence.validation:
                        logging.warning(
                            f"Convergence resolution completed but the generated "
                            f"code still differs from the imported state: "
                            f"{convergence.feedback}"
                        )
                    plan_after_import = convergence.terraform_plan or plan_after_import

                # Step 6 — Gate. The import report describes what is now
                # tracked in state, so it needs the per-resource outcome and
                # not only the plan: after a clean convergence the plan is
                # empty, which on its own says nothing about the round.
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
                check = await self.__compliance_svc.check(
                    request=ctx.history.get_first_turn().user,
                    conventions=conventions,
                    plan=plan_after_import,
                )
                if not check.passed:
                    if not await DatabaseService.set_lock(ctx.id, True):
                        raise SetLockError(
                            message="Error updating DB session lock.",
                            error_code=500,
                        )
                    await NotificationServiceClient.notify_compliance_failure(
                        ctx.id, ctx.user_id, check.summary
                    )
                elif not await DatabaseService.set_lock(ctx.id, False):
                    raise SetLockError(
                        message="Error updating DB session lock.",
                        error_code=500,
                    )
            except Exception as e:
                logging.error(
                    f"Import with session id: {ctx.id} aborted with "
                    f"{type(e).__name__}: {e}"
                )
                raise
            finally:
                await self.__session_svc.save()

        return background_task
