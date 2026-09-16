# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from abc import ABC, abstractmethod

from src.domains.dto import TerraformValidationDTO


class ITerraform(ABC):
    @abstractmethod
    async def validate(
        self,
        targets: list[str],
        get_drift: bool,
    ) -> TerraformValidationDTO:
        """
        Validates Terraform infrastructure changes against specific targets.

        This method performs comprehensive validation of Terraform changes, including:
        - Terraform plan execution
        - Optional infrastructure drift detection

        Args:
            targets (list[str]): List of specific Terraform resource targets to validate.
                                 If empty, validates all resources in the configuration.
                                 Each target should be in the format 'module.name.resource_type.resource_name'
                                 or 'resource_type.resource_name'.
            get_drift (bool): Output resource changes as part of the `feedback` attribute DTO

        Returns:
            TerraformValidationDTO: A data transfer object containing:
                - validation (bool): True if validation passes, False if issues are found
                - feedback (str): Detailed feedback message explaining validation results,
                                 including specific issues found and recommended actions, or
                                 a parsed list of terraform changes (drift).

        Raises:
            ExceptionHandler: When terraform plan format is incompatible or validation fails
                             due to infrastructure issues
            ValidationError: When the provided targets are invalid
            InfrastructureError: When there are issues connecting to cloud provider APIs
                                or downloading terraform artifacts

        Example:
            ```python
            validator = TerraformDrift(...)
            result = await validator.validate(
                targets=["azurerm_storage_account.main", "azurerm_resource_group.rg"],
                get_drift=False,
            )

            if result.validation:
                print("Validation passed!")
            else:
                print(f"Validation failed: {result.feedback}")
            ```

        Note:
            - This method is async and should be awaited
            - Validation can includes drift detection by comparing current state with planned changes
            - The method may download and analyze terraform plan artifacts from remote storage
            - Resource changes (drift option) are filtered to exclude known exceptions and benign modifications
            - A successful plan is written to the configured session plan
              filename (``paths.session_plan_filename``) inside the workspace;
              pinning that workspace at round end is what makes the plan
              appliable later
        """

    @abstractmethod
    async def apply(self) -> TerraformValidationDTO:
        """
        Applies the plan artifact saved in this instance's workspace.

        The workspace is the session's pinned slot: the already-initialized
        workspace promoted at the end of the last successful generate/drift
        round, still holding the plan it produced. A single ``apply`` job
        executes that plan — no init and no plan run at apply time, so the
        applied changes cannot diverge from the reviewed ones. The plan's
        own target scope is inherited (terraform forbids ``-target`` with a
        saved plan).

        Returns:
            TerraformValidationDTO: A data transfer object containing:
                - validation (bool): True if the apply succeeded
                - feedback (str): stderr of the apply when unsuccessful
                - terraform_plan (str): stdout of the apply command
                - terraform_targets (list[str]): always empty; the targets
                  are recorded inside the saved plan

        Raises:
            ExceptionHandler: When the IaC service is unreachable, times out,
                             or reports a service-level job failure
        """
