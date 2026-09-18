# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from abc import ABC, abstractmethod

from src.domains.dto import TerraformApplyDTO, TerraformDriftDTO, TerraformPlanDTO
from src.domains.value_objects import PlanRef


class ITerraform(ABC):
    @abstractmethod
    async def plan(self, targets: list[str]) -> TerraformPlanDTO:
        """
        Validates the workspace's Terraform code and plans the given targets.

        Runs the engine's validation of the configuration and then produces
        a plan against live cloud state, saving it to the configured session
        plan filename (``paths.session_plan_filename``) inside the workspace.
        Pinning that workspace at round end is what makes the plan appliable
        later.

        Args:
            targets (list[str]): List of specific Terraform resource targets to plan.
                                 If empty, plans all resources in the configuration.
                                 Each target should be in the format 'module.name.resource_type.resource_name'
                                 or 'resource_type.resource_name'.

        Returns:
            TerraformPlanDTO: A data transfer object containing:
                - ok (bool): True when the code is valid and the plan succeeded
                - feedback (str): the engine's stderr when unsuccessful, which is
                                  what the generation loop feeds back to the model
                - stdout (str): the plan text, present even on failure
                - targets (list[str]): the targets this call planned for
                - plan (PlanRef | None): the plan artifact just written, or None
                                         when ``ok`` is False

        Raises:
            ExceptionHandler: When the IaC service is unreachable, times out,
                             or reports a service-level job failure

        Example:
            ```python
            terraform = Terraform(...)
            result = await terraform.plan(
                targets=["azurerm_storage_account.main", "azurerm_resource_group.rg"],
            )

            if result.ok:
                print("Validation passed!")
            else:
                print(f"Validation failed: {result.feedback}")
            ```
        """

    @abstractmethod
    async def drift(self, plan: PlanRef) -> TerraformDriftDTO:
        """
        Reads infrastructure drift out of an existing plan artifact.

        Inspects the plan ``plan`` identifies and diffs each resource's
        ``before`` and ``after`` states, inverting the result into "make the
        code match the infrastructure" changes. No plan is produced here, so
        a caller that already has a plan for these targets pays for no second
        one.

        A ref the workspace has moved past is re-planned rather than
        refused: the ref guards a best-effort optimization, so a caller that
        held one too long gets a correct answer instead of an error.

        Args:
            plan (PlanRef): the artifact to read, as returned by ``plan``.
                            It must belong to this instance's workspace.

        Returns:
            TerraformDriftDTO: A data transfer object containing:
                - in_sync (bool): True when the plan shows no differences
                - drift (str): the parsed list of Terraform changes, as JSON
                - feedback (str): the engine's stderr when the read itself failed
                - stdout (str): the plan text the drift was read from
                - plan (PlanRef | None): the artifact actually read, None when
                                         the read failed

        Raises:
            ExceptionHandler: When ``plan`` belongs to another workspace, when
                             the engine returns unparseable JSON, or when the
                             IaC service is unreachable, times out, or reports
                             a service-level job failure
        """

    @abstractmethod
    async def apply(self) -> TerraformApplyDTO:
        """
        Applies the plan artifact saved in this instance's workspace.

        The workspace is the session's pinned slot: the already-initialized
        workspace promoted at the end of the last successful generate
        round (drift rounds never pin), still holding the plan it
        produced. A single ``apply`` job
        executes that plan — no init and no plan run at apply time, so the
        applied changes cannot diverge from the reviewed ones. The plan's
        own target scope is inherited (terraform forbids ``-target`` with a
        saved plan).

        Returns:
            TerraformApplyDTO: A data transfer object containing:
                - ok (bool): True if the apply succeeded
                - stdout (str): stdout of the apply command
                - feedback (str): stderr of the apply when unsuccessful

        Raises:
            ExceptionHandler: When the IaC service is unreachable, times out,
                             or reports a service-level job failure
        """
