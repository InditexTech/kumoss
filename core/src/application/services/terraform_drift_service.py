# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from src.domains.dto import TerraformDriftDTO, TerraformPlanDTO
from src.domains.entities import History, SessionContext
from src.domains.interfaces import ITerraform
from src.domains.services import (
    ArtifactStorageService,
    SessionService,
    TaskService,
    TemplateOrchestrationService,
    TerraformValidationService,
)
from src.domains.value_objects import Conventions, PlanRef
from src.shared.constants import (
    ContentType,
    OperationType,
    SessionStatus,
)
from src.shared.logger import logging

# Status copy. None of these embeds raw terraform output, so none is
# paraphrased: the unresolved-drift message is built inline and is the
# only one the model rewrites before the UI renders it verbatim.
_ASSESSING = "Assessing drift on the targeted infrastructure."
_IN_SYNC = "No drift found; the targeted infrastructure is synchronized."


class TerraformDriftService:
    def __init__(
        self,
        session_context: SessionContext,
        session_service: SessionService,
        template_service: TemplateOrchestrationService,
        validation_service: TerraformValidationService,
        terraform_service: ITerraform,
        split_service: TaskService,
        artifact_service: ArtifactStorageService,
    ):
        self.__ctx = session_context
        self.__session_svc = session_service
        self.__template_svc = template_service
        self.__validation_svc = validation_service
        self.__terraform_svc = terraform_service
        self.__split_svc = split_service
        self.__artifact_svc = artifact_service

    async def detect_and_resolve_drift(
        self,
        plan: PlanRef | None,
        filter_session_changes: bool,
        targets: list[str],
        conventions: Conventions,
        max_iterations: int,
    ) -> TerraformDriftDTO:
        """Read drift out of a plan and reconcile it, bounded by ``max_iterations``.

        A check reads drift out of a plan rather than producing one, so
        ``plan`` is the plan to start from: a generate round hands over the
        one it just validated, which is why its pre-check costs no extra
        plan, and a dedicated drift session passes None because nothing has
        planned its workspace yet. Every reconciliation group re-plans
        through ``validator``, and the last of those is what the next
        iteration reads. An iteration whose split produced no operations
        leaves nothing behind, so the next one has no ref and plans for
        itself — which is what keeps every iteration that could have
        changed reading live state.
        """
        drift = TerraformDriftDTO.empty()
        exclusions: list[str] = []

        def resolved(result: TerraformDriftDTO) -> TerraformDriftDTO:
            result.excluded = exclusions
            return result

        async def validator(history: History) -> TerraformPlanDTO:
            return await self.__terraform_svc.plan(targets=targets)

        for i in range(max_iterations):
            logging.debug(f"Drift report no: {i + 1}/{max_iterations}")

            _ = await self.__session_svc.update_status(
                msg=_ASSESSING,
                status=SessionStatus.RECONCILING,
            )

            if plan is None:
                plan_result = await self.__terraform_svc.plan(targets=targets)
                if plan_result.plan is None:
                    logging.error(f"Drift check could not plan: {plan_result.feedback}")
                    return resolved(
                        TerraformDriftDTO(
                            in_sync=False,
                            drift="",
                            feedback=plan_result.feedback,
                            stdout=plan_result.stdout,
                            plan=None,
                        )
                    )
                plan = plan_result.plan

            drift = await self.__terraform_svc.drift(plan=plan)

            if drift.in_sync:
                break

            await self.__store_drift(drift, targets)

            if drift.feedback:
                logging.error(f"Drift could not be read: {drift.feedback}")
                return resolved(drift)

            operations: list[list[str]] = await self.__split_svc.split_task(
                task=drift.drift,
            )
            if filter_session_changes:
                operations = await self.__split_svc.filter_reconciliation(
                    operations=operations,
                )
                if not operations:
                    logging.warning(
                        "Drift pre-check completed, remaining drift corresponds to session changes"
                    )
                    return resolved(drift)

            filtered = await self.__split_svc.filter_exceptions(operations=operations)
            if filtered.excluded:
                note = filtered.explanation or "; ".join(filtered.excluded)
                logging.warning(f"Drift exception rules excluded operations: {note}")
                exclusions.append(note)
            if operations and not filtered.kept:
                logging.warning(
                    "Drift remediation stopped, every operation is covered by the "
                    + f"drift exception rules: {exclusions}"
                )
                return resolved(drift)
            operations = filtered.kept

            plan = None
            for idx, group_ops in enumerate(operations):
                logging.debug(f"Operation {idx + 1}/{len(operations)}: {group_ops}")
                result = await self.__validation_svc.generate_and_validate(
                    q=str(group_ops),
                    ctx=self.__ctx,
                    conventions=conventions,
                    include_forbidden_actions=False,
                    operation_type=OperationType.DRIFT,
                    validator=validator,
                )
                plan = result.plan

        if plan is not None and drift.plan is not None and plan != drift.plan:
            drift = await self.__terraform_svc.drift(plan=plan)

        if drift.in_sync:
            logging.warning("Drift pre-check completed, resources are synchronized")
        else:
            remaining = f"Drift resolution completed but issues remain: {drift.drift}"
            logging.warning(remaining)

        return resolved(drift)

    async def __store_drift(
        self,
        drift: TerraformDriftDTO,
        targets: list[str],
    ) -> None:
        if drift.drift:
            _ = await self.__artifact_svc.store_terraform_plan(
                session_id=self.__ctx.id,
                round_id=self.__ctx.round_id,
                targets=targets,
                content=drift.drift,
                content_type=ContentType.TEXT,
                metadata={"type": "drift"},
            )
