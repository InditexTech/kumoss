# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from src.domains.dto import TerraformDriftDTO, TerraformPlanDTO
from src.domains.entities import History, SessionContext
from src.domains.interfaces import ITerraform
from src.domains.services import (
    ArtifactStorageService,
    SessionService,
    TemplateOrchestrationService,
    TerraformValidationService,
    TaskService,
)
from src.domains.value_objects import Conventions, PlanRef
from src.shared.constants import ContentType, PromptsLibrary, SessionStatus
from src.shared.logger import logging

# Status copy. None of these embeds raw terraform output, so none is
# paraphrased: the unresolved-drift message is built inline and is the
# only one the model rewrites before the UI renders it verbatim.
_ASSESSING = "Assessing drift on the targeted infrastructure."
_IN_SYNC = "No drift found; the targeted infrastructure is synchronized."
_SESSION_CHANGES = (
    "Drift check completed; the remaining differences are this session's own changes."
)
_EXCLUDED = (
    "Drift check completed; the remaining differences are covered "
    "by the drift exception rules."
)


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

            # Above the plan on purpose. A dedicated drift session plans
            # its own workspace below and that plan is part of the
            # assessment; the drift diff stored below only renders under
            # this entry if the status precedes it (the read model links
            # artifacts to statuses by time); and an in-sync round breaks
            # out without storing anything, so this is the only record
            # that the check ran at all.
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
                    await self.__announce(_SESSION_CHANGES)
                    return resolved(drift)

            filtered = await self.__split_svc.filter_exceptions(operations=operations)
            if filtered.excluded:
                note = filtered.explanation or "; ".join(filtered.excluded)
                logging.warning(f"Drift exception rules excluded operations: {note}")
                exclusions.append(note)
            if operations and not filtered.kept:
                logging.warning(
                    "Drift remediation stopped, every operation is covered by the "
                    f"drift exception rules: {exclusions}"
                )
                await self.__announce(_EXCLUDED)
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
                    validator=validator,
                )
                plan = result.plan

        if plan is not None and drift.plan is not None and plan != drift.plan:
            drift = await self.__terraform_svc.drift(plan=plan)

        if drift.in_sync:
            logging.warning("Drift pre-check completed, resources are synchronized")
            await self.__announce(_IN_SYNC)
        else:
            remaining = f"Drift resolution completed but issues remain: {drift.drift}"
            logging.warning(remaining)
            await self.__announce(remaining, rewrite=True)

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
                is_drift=True,
            )

    async def __announce(self, msg: str, rewrite: bool = False) -> None:
        """Persist the phase's conclusion as a status entry.

        ``rewrite`` routes the message through the small model, which is
        needed only when it embeds raw terraform output: the UI renders
        status messages verbatim. The literals are already prose, and the
        pre-check runs on every generate round, so paraphrasing them
        would cost an LLM call per round for nothing.
        """
        _ = await self.__session_svc.update_status(
            msg=msg,
            prompt=await self.__template_svc.render(PromptsLibrary.STATUS_UPDATE)
            if rewrite
            else None,
            status=SessionStatus.RECONCILING,
            history=self.__ctx.history if rewrite else None,
        )
