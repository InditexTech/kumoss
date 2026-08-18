# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from abc import ABC, abstractmethod

from src.domains.dto import TerraformValidationDTO


class ITerraform(ABC):
    @abstractmethod
    async def validate(
        self,
        branch: str,
        targets: list[str],
        get_drift: bool = False,
    ) -> TerraformValidationDTO:
        """
        Validates Terraform infrastructure changes against a specific branch and targets.

        This method performs comprehensive validation of Terraform changes, including:
        - Terraform plan execution
        - Optional infrastructure drift detection

        Args:
            branch (str): The git branch name to validate against. This branch should
                         contain the Terraform configuration to be validated.
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
            ValidationError: When the provided branch or targets are invalid
            InfrastructureError: When there are issues connecting to cloud provider APIs
                                or downloading terraform artifacts

        Example:
            ```python
            validator = TerraformDrift(...)
            result = await validator.validate(
                branch="feature/new-infrastructure",
                targets=["azurerm_storage_account.main", "azurerm_resource_group.rg"]
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
        """
        pass

    @abstractmethod
    async def apply(
        self,
        targets: list[str],
    ) -> TerraformValidationDTO:
        """
        Applies Terraform infrastructure changes for the given targets.

        Runs ``init`` -> ``plan`` (scoped to ``targets``) -> ``apply`` against
        the session's workspace. The applied plan is computed at apply time in
        the session's fresh workspace clone — it is not a pinned plan artifact
        from a previous review.

        Args:
            targets (list[str]): List of specific Terraform resource targets to apply.
                                 If empty, applies all resources in the configuration.

        Returns:
            TerraformValidationDTO: A data transfer object containing:
                - validation (bool): True if the apply succeeded, False if any
                                     step exited non-zero
                - feedback (str): stderr of the failing step when unsuccessful
                - terraform_plan (str): stdout of the apply command

        Raises:
            ExceptionHandler: When the IaC service is disabled, unreachable,
                             times out, or reports a service-level job failure
        """
        pass
