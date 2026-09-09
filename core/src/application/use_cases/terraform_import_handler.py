# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from collections.abc import Coroutine
from typing import Callable, Any, cast

from src.application.exceptions import SetLockError, TerraformValidationFailedError
from src.application.services.requests_filter_service import RequestsFilterService
from src.application.services.report_service import ReportService
from src.application.services.terraform_drift_service import TerraformDriftService
from src.application.services.terraform_import_service import TerraformImportService
from src.domains.dto import TerraformValidationDTO, ToolResultDTO
from src.domains.entities import History
from src.domains.entities.session import SessionContext
from src.domains.interfaces import ITerraform
from src.domains.services import (
    ComplianceCheckService,
    SessionService,
    TemplateOrchestrationService,
    TerraformValidationService,
)
from src.domains.services.database_service import DatabaseService
from src.domains.services.llm_service import LLMOrchestrationService
from src.domains.services.tool_service import ToolOrchestrationService
from src.infrastructure.external.notification_service import NotificationServiceClient
from src.shared.config import system_config
from src.shared.constants import (
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
        self.__drift_svc = drift_service
        self.__compliance_svc = compliance_service
        self.__llm_svc = llm_service
        self.__tool_svc = tool_service
        self.__ctx = session_ctx

    async def handle(self, q: str) -> Callable[[], Coroutine[Any, Any, None]]:
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
                conventions = await self.__template_svc.compose_template(q, ctx.history)

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

                # Step 1 — Discovery
                unmanaged_ids = await self.__import_svc.get_unmanaged_resources(
                    scope_id=ctx.scope_id,
                    terraform_provider=ctx.terraform_prv,
                )
                if not unmanaged_ids:
                    msg = "No unmanaged resources found in scope."
                    ctx.history.append_turn(q, msg)
                    _ = await self.__session_svc.update_status(
                        msg=msg,
                        status=SessionStatus.UNCOMPLETED,
                    )
                    return

                # Step 2 — Selection (iac_filter agent)
                filter_result: ToolResultDTO = await self.__llm_svc.generate(
                    query=q,
                    tools=[
                        self.__tool_svc.get_sentinel_tool(
                            context=ToolContext.IAC_FILTER,
                        )
                    ],
                    prompt=await self.__template_svc.render(
                        prompt=PromptsLibrary.IAC_FILTER,
                        unmanaged_ids=unmanaged_ids,
                        resources=conventions.templates,
                        abbreviations=conventions.abbreviations,
                    ),
                    history=ctx.history,
                )
                selected_ids: list[str] = cast(
                    list[str], filter_result.result["selected_resource_ids"]
                )
                filter_explanation: str = cast(str, filter_result.result["explanation"])

                if not selected_ids:
                    ctx.history.append_turn(q, filter_explanation)
                    _ = await self.__session_svc.update_status(
                        msg=filter_explanation,
                        status=SessionStatus.UNCOMPLETED,
                    )
                    return

                # Step 3 — Config generation (IAC_IMPORT prompt + IAC_IMPORT sentinel)
                async def validation_callback(
                    local_history: History,
                ) -> TerraformValidationDTO:
                    return await self.__terraform_svc.validate(
                        targets=[],
                        get_drift=False,
                    )

                validation = await self.__validation_svc.generate_and_validate(
                    q=q,
                    ctx=ctx,
                    conventions=conventions,
                    include_forbidden_actions=False,
                    validator=validation_callback,
                    prompt_key=PromptsLibrary.IAC_IMPORT,
                    sentinel_context=ToolContext.IAC_IMPORT,
                    prompt_kwargs={"selected_ids": selected_ids},
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

                # Step 4 — Import execution
                generation_result = self.__validation_svc.last_generation_result
                imports: list[tuple[str, str]] = [
                    (entry["address"], entry["resource_id"])
                    for entry in (
                        generation_result.result.get("imports", [])
                        if generation_result
                        else []
                    )
                ]
                if not imports:
                    logging.warning(
                        f"There is nothing to import: "
                        f"the iac_import sentinel returned an empty 'imports' mapping "
                        f"for selected ids {selected_ids}"
                    )
                import_results = await self.__import_svc.import_resources(imports)

                failed = [r for r in import_results if not r.validation]
                if failed:
                    logging.warning(
                        f"{len(failed)}/{len(import_results)} resource imports failed"
                    )

                # Step 5 — Convergence: the imported state now mirrors the real
                # resources, but the generated blocks hold guessed arguments.
                # Reuse the drift resolution loop so the LLM rewrites the code
                # until a plan over the imported addresses reports no changes.
                imported_addresses = [
                    r.terraform_targets[0]
                    for r in import_results
                    if r.validation and r.terraform_targets
                ]
                report_content = validation.terraform_plan
                if imported_addresses:

                    async def convergence_callback(
                        local_history: History,
                    ) -> TerraformValidationDTO:
                        return await self.__terraform_svc.validate(
                            targets=imported_addresses,
                            get_drift=False,
                        )

                    convergence = await self.__drift_svc.detect_and_resolve_drift(
                        targets=imported_addresses,
                        conventions=conventions,
                        max_iterations=system_config.orchestration.max_drift_reports,
                        validator=convergence_callback,
                    )
                    if not convergence.validation:
                        logging.warning(
                            f"Convergence resolution completed but the generated "
                            f"code still differs from the imported state: "
                            f"{convergence.feedback}"
                        )
                    report_content = convergence.terraform_plan or report_content

                # Step 6 — Gate
                report = await self.__report_svc.generate_report(
                    ctx=ctx,
                    type=ReportType.IMPORT,
                    content=report_content,
                )
                check = await self.__compliance_svc.check(
                    history=ctx.history,
                    conventions=conventions,
                    report=report,
                )
                if not check.passed:
                    if not await DatabaseService.set_lock(ctx.id, True):
                        raise SetLockError(
                            message="Error updating DB session lock.",
                            error_code=500,
                        )
                    await NotificationServiceClient.notify_compliance_failure(
                        session_id=ctx.id,
                        summary=check.summary,
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
