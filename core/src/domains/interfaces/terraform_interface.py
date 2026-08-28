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

    @abstractmethod
    async def state_resource_ids(
        self,
    ) -> list[str]:
        """
        Retrieves the provider-assigned IDs of every managed resource
        instance currently tracked in the Terraform state.

        Submits a ``state pull`` job via ``POST /v1/import/state-resource-ids``
        and parses the result. On exit code 0, ``stdout`` is a JSON array of
        resource ID strings extracted from the state's managed resource
        instances (the ``attributes.id`` of each instance). An empty state
        returns ``[]``. The workspace must already be initialised.

        Returns:
            list[str]: Provider-assigned resource IDs of all managed
                resources in the state (e.g. Azure resource IDs, AWS ARNs,
                GCP self-links). Empty when the state tracks nothing.

        Raises:
            ExceptionHandler: When the IaC service is disabled, unreachable,
                             times out, reports a service-level job failure,
                             or ``state pull`` exits non-zero.
        """
        pass

    @abstractmethod
    async def scope_resource_ids(
        self,
        scope_id: str,
        terraform_provider: str,
    ) -> list[str]:
        """
        Lists the resource IDs that exist in a cloud provider scope.

        Submits a cloud-provider query via ``POST /v1/import/scope-resource-ids``.
        This does **not** read Terraform state — it queries the cloud control
        plane directly using the provider's native listing API:

        - ``azure``: Azure Resource Graph — resource and resource-container
          IDs whose id contains ``scope_id``.
        - ``gcp``: Cloud Asset Inventory — asset names of the project's
          resources plus the IAM role names bound in the project.
        - ``aws``: Resource Groups Tagging API — resource ARNs across the
          account's enabled regions.

        On exit code 0, ``stdout`` is a JSON array of provider-native resource
        ID strings. Non-zero ``exit_code`` with diagnostics in ``stderr`` is a
        normal outcome (e.g. scope not found, credentials issue) — the job
        still ends as ``succeeded``.

        Args:
            scope_id (str): Cloud provider scope to list — Azure: subscription
                id, GCP: project id, AWS: account id.
            terraform_provider (str): Cloud provider to query. One of
                ``azure``, ``gcp``, ``aws``.

        Returns:
            list[str]: Provider-native resource IDs present in the scope.

        Raises:
            ExceptionHandler: When the IaC service is disabled, unreachable,
                             times out, or reports a service-level job failure.
        """
        pass

    @abstractmethod
    async def import_resource(
        self,
        address: str,
        resource_id: str,
    ) -> TerraformValidationDTO:
        """
        Imports an existing cloud resource into the Terraform state.

        Runs ``terraform import <address> <resource_id>`` via
        ``POST /v1/import`` against the workspace. The target resource
        block (``address``) must already exist in the ``.tf`` configuration
        files, and the workspace must already be initialised (submit an
        ``init`` job first).

        Args:
            address (str): The Terraform resource address to import into,
                e.g. ``azurerm_storage_account.main``.
            resource_id (str): The provider-specific identifier of the
                existing cloud resource, e.g. an Azure resource ID or an
                AWS ARN.

        Returns:
            TerraformValidationDTO: A data transfer object containing:
                - validation (bool): True if the import succeeded (exit
                  code 0), False otherwise.
                - feedback (str): stderr of the import command when
                  unsuccessful; empty on success.
                - terraform_plan (str): stdout of the import command.

        Raises:
            ExceptionHandler: When the IaC service is disabled, unreachable,
                             times out, or reports a service-level job failure.
        """
        pass
