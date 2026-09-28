# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import json
from collections.abc import Coroutine
from dataclasses import asdict
from typing import Callable, Any

from src.application.exceptions import TerraformValidationFailedError
from src.application.services.requests_filter_service import RequestsFilterService
from src.application.services.report_service import ReportService
from src.application.services.terraform_drift_service import TerraformDriftService
from src.application.services.terraform_import_service import TerraformImportService
from src.domains.dto import (
    TerraformImportAttempt,
    TerraformImportDTO,
    TerraformPlanDTO,
    ValidationResultDTO,
)
from src.domains.entities import History
from src.domains.entities.session import SessionContext
from src.domains.exceptions import ValidationLoopExceededError
from src.domains.interfaces import ITerraform
from src.domains.services import (
    SessionService,
    TaskService,
    TemplateOrchestrationService,
    TerraformImportAddressService,
    TerraformTargetService,
    TerraformValidationService,
)
from src.domains.value_objects import Conventions
from src.shared.config import system_config
from src.shared.constants import (
    OperationType,
    PromptsLibrary,
    ReportType,
    SessionStatus,
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
        task_service: TaskService,
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
        self.__task_svc = task_service
        self.__ctx = session_ctx

    async def __report_nothing_to_import(
        self, q: str, msg: str, excluded: list[str]
    ) -> None:
        """Close a round that found nothing to import with an empty report.

        The scope could not be listed, holds nothing importable, is already
        fully managed or withheld by the import exception list, or the
        request targets nothing unmanaged — ``msg`` says which, and
        ``excluded`` names what the exception list withheld. Reporting
        instead of dead-ending leaves the session completed: the runner
        marks any handler that returns without setting UNCOMPLETED as
        completed.
        """
        ctx = self.__ctx
        ctx.history.append_turn(q, msg)
        _ = await self.__report_svc.generate_report(
            ctx=ctx,
            type=ReportType.IMPORT,
            content=json.dumps(
                {
                    "selected_resource_ids": [],
                    "excluded_resource_ids": excluded,
                    "import_results": {"imported": [], "failed": []},
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
                    await self.__report_nothing_to_import(
                        q, discovery.feedback, discovery.excluded
                    )
                    return

                if is_partial:
                    filtered = await self.__task_svc.filter_imports(
                        query=q,
                        unmanaged_ids=unmanaged_ids,
                        conventions=conventions,
                        history=ctx.history,
                    )
                    unmanaged_ids = filtered.selected

                    if not unmanaged_ids:
                        await self.__report_nothing_to_import(
                            q,
                            msg=filtered.explanation
                            or "No unmanaged resource matched the request.",
                            excluded=discovery.excluded,
                        )
                        return

                async def plan_callback(
                    local_history: History,
                ) -> TerraformPlanDTO:
                    return await self.__terraform_svc.plan(
                        targets=await self.__target_svc.generate_session(local_history),
                    )

                plan_result = await self.__validation_svc.generate_and_validate(
                    q="Create a Terraform resource block for each of these "
                    + "\n".join(f"- {rid}" for rid in unmanaged_ids),
                    ctx=ctx,
                    conventions=Conventions.empty(),
                    include_forbidden_actions=False,
                    operation_type=OperationType.IMPORT,
                    validator=plan_callback,
                    max_iterations=system_config.orchestration.max_import_iteration,
                )

                imported: set[TerraformImportAttempt] = set()
                failed: set[TerraformImportAttempt] = set()
                import_targets: list[str] = plan_result.targets

                async def import_callback(
                    local_history: History,
                ) -> ValidationResultDTO:
                    import_cmds: set[
                        TerraformImportAttempt
                    ] = await self.__import_address_svc.get_import_addresses(
                        failed or unmanaged_ids
                    )
                    import_cmds.difference_update(imported)
                    outcome = await self.__import_svc.import_resources(import_cmds)
                    imported.update(outcome.imported)
                    failed.difference_update(outcome.failed)
                    failed.update(outcome.failed)
                    failed.difference_update(imported)
                    logging.debug(
                        f"import_cmds: {[r.address for r in import_cmds]}\n"
                        + f"imported: {[r.address for r in imported]}\n"
                        + f"failed: {[r.address for r in failed]}\n"
                    )
                    return TerraformImportDTO(
                        imported=imported,
                        failed=failed,
                    )

                async def split_errors(errors: str) -> str:
                    return await self.__task_svc.split_errors(
                        errors=errors, operation_type=OperationType.IMPORT
                    )

                import_results: ValidationResultDTO = await import_callback(ctx.history)
                if not import_results.ok:
                    try:
                        import_results = await self.__validation_svc.generate_and_validate(
                            q=await split_errors(import_results.feedback),
                            ctx=ctx,
                            conventions=Conventions.empty(),
                            include_forbidden_actions=False,
                            operation_type=OperationType.GENERATE,
                            validator=import_callback,
                            max_iterations=system_config.orchestration.max_import_iteration,
                            refine_feedback=split_errors,
                        )
                    except ValidationLoopExceededError as e:
                        if not isinstance(e.result, TerraformImportDTO):
                            raise
                        import_results = e.result

                if import_results.stdout:
                    drift = await self.__drift_svc.detect_and_resolve_drift(
                        plan=None,
                        filter_session_changes=False,
                        targets=import_targets,
                        conventions=conventions,
                        max_iterations=system_config.orchestration.max_drift_reports,
                    )
                    if drift.feedback:
                        fail_msg = await self.__report_svc.summarize_problem(
                            feedback=drift.feedback,
                            history=ctx.history,
                        )
                        raise TerraformValidationFailedError(
                            message=fail_msg,
                            error_code=500,
                        )

                _ = await self.__report_svc.generate_report(
                    ctx=ctx,
                    type=ReportType.IMPORT,
                    content=json.dumps(
                        {
                            "selected_resource_ids": unmanaged_ids,
                            "excluded_resource_ids": discovery.excluded,
                            "import_results": {
                                "imported": [asdict(a) for a in imported],
                                "failed": [asdict(a) for a in failed],
                            },
                        }
                    ),
                )
            finally:
                await self.__session_svc.save()

        return background_task
