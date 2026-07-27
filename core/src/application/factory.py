# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

# Domain layer imports
from src.domains.interfaces import ILLMProvider, ITerraformValidator
from src.domains.interfaces.filesystem_interface import IFileSystem
from src.domains.interfaces.git_interface import IGit
from src.domains.services import (
    ComplianceCheckService,
    TemplateOrchestrationService,
    TerraformTargetService,
    TerraformValidationService,
    ToolOrchestrationService,
    SessionService,
    LLMOrchestrationService,
)

# Infrastructure layer imports
from src.domains.services.task_split_service import TaskSplitService
from src.infrastructure.external.gemini_web_search import GeminiWebSearch
from src.infrastructure.tools.tool_registry import ToolRegistry
from src.infrastructure.filesystem.file_system import FileSystemUtils
from src.infrastructure.filesystem.git_utils import GitUtils
from src.infrastructure.templates.factory import TemplateFactory
from src.infrastructure.llm.factory import LLMFactory
from src.infrastructure.validators.factory import ValidatorFactory

# Application layer imports
from src.application.services import (
    FilterRequestService,
    GeneratePayloadService,
    ProjectSetupService,
    TerraformDriftService,
)
from src.application.use_cases import (
    ComplianceCheckHandler,
    TerraformCRUDHandler,
    TerraformDriftHandler,
    TerraformApplyHandler,
)
from pathlib import Path

from src.application.dto import SessionContext

# Shared imports
from src.shared.constants import (
    TemplateProvider,
    LLMProvider,
)
from src.shared.config import system_config


class HandlerFactory:
    def __init__(
        self,
        *,
        session_ctx: SessionContext,
        call_dir: Path,
        q: str,
        terraform_targets: list[str] | None = None,
        is_partial: bool = False,
    ):
        self.session_ctx = session_ctx
        self.call_dir = call_dir
        self.q = q
        self.terraform_targets = terraform_targets or []
        self.is_partial = is_partial

    # --- Providers for Infrastructure Components ---
    # These providers create the concrete implementations for the utils

    def _get_file_utils(self) -> FileSystemUtils:
        root = self.call_dir
        if self.session_ctx.iac_path:
            root = root / self.session_ctx.iac_path
        return FileSystemUtils(
            root=root,
            file_ext=["tf", "tfvars"],
        )

    def _get_git_utils(self, file_utils: IFileSystem) -> GitUtils:
        return GitUtils(
            cwd=file_utils.project_root,
            branch=self.session_ctx.branch_name,
        )

    # --- Providers for Domain Services ---
    # These providers construct the domain services, injecting infrastructure components.

    @staticmethod
    def get_llm_adapter(provider: LLMProvider, temperature: float) -> ILLMProvider:
        return LLMFactory(
            provider=provider,
            temperature=temperature,
        ).get()

    def _get_llm_service(
        self,
        tool_service: ToolOrchestrationService,
        main_llm: LLMProvider,
        main_temp: float,
        small_llm: LLMProvider,
        small_temp: float,
    ) -> LLMOrchestrationService:
        return LLMOrchestrationService(
            main_llm_provider=self.get_llm_adapter(
                provider=main_llm,
                temperature=main_temp,
            ),
            small_llm_provider=self.get_llm_adapter(
                provider=small_llm,
                temperature=small_temp,
            ),
            tool_service=tool_service,
        )

    def _get_tool_registry(
        self, file_utils: IFileSystem, git_utils: IGit
    ) -> ToolRegistry:
        return ToolRegistry(
            filesystem=file_utils,
            git=git_utils,
            web_search=GeminiWebSearch(
                gemini=self.get_llm_adapter(LLMProvider.GEMINI_FLASH, 0.5)
            ),
        )

    def _get_tool_service(
        self, tool_registry: ToolRegistry
    ) -> ToolOrchestrationService:
        return ToolOrchestrationService(tool_registry=tool_registry)

    def _get_session_service(self, second_llm_service: LLMOrchestrationService):
        return SessionService(second_llm_service)

    def _get_template_service(
        self,
        llm_service: LLMOrchestrationService,
        tool_service: ToolOrchestrationService,
        file_utils: IFileSystem,
    ):
        template_adapter = TemplateFactory(
            template_provider=getattr(TemplateProvider, self.session_ctx.cloud.upper()),
            cwd=str(file_utils.project_root),
        ).get()
        return TemplateOrchestrationService(
            templates=template_adapter,
            llm_service=llm_service,
            tool_service=tool_service,
        )

    def _get_terraform_target_service(
        self,
        tool_service: ToolOrchestrationService,
        main_llm_service: LLMOrchestrationService,
        template_service: TemplateOrchestrationService,
    ) -> TerraformTargetService:
        return TerraformTargetService(
            tool_service=tool_service,
            llm_service=main_llm_service,
            template_service=template_service,
        )

    def _get_terraform_split_service(
        self,
        tool_service: ToolOrchestrationService,
        main_llm_service: LLMOrchestrationService,
        template_service: TemplateOrchestrationService,
    ) -> TaskSplitService:
        return TaskSplitService(
            tool_service=tool_service,
            llm_service=main_llm_service,
            template_service=template_service,
        )

    def _get_validator_provider(
        self,
        file_utils: FileSystemUtils,
        session_service: SessionService,
    ) -> ITerraformValidator:
        return ValidatorFactory(
            session_service=session_service,
            file_utils=file_utils,
        ).get()

    def _get_terraform_validation_service(
        self,
        git_utils: GitUtils,
        template_service: TemplateOrchestrationService,
        main_llm_service: LLMOrchestrationService,
        session_service: SessionService,
        tool_service: ToolOrchestrationService,
        target_service: TerraformTargetService,
        validator_provider: ITerraformValidator,
    ) -> TerraformValidationService:
        return TerraformValidationService(
            validator=validator_provider,
            git=git_utils,
            template_service=template_service,
            llm_service=main_llm_service,
            session_service=session_service,
            tool_orchestration_service=tool_service,
            target_service=target_service,
        )

    # --- Providers for Application Building Blocks ---

    def _get_project_setup_service(
        self,
        git_utils: GitUtils,
        file_utils: FileSystemUtils,
    ) -> ProjectSetupService:
        return ProjectSetupService(
            git=git_utils,
            filesystem=file_utils,
        )

    def _get_filter_request_service(
        self,
        second_llm_service: LLMOrchestrationService,
        tool_svc: ToolOrchestrationService,
        template_service: TemplateOrchestrationService,
    ):
        return FilterRequestService(
            second_llm_service=second_llm_service,
            tool_service=tool_svc,
            template_service=template_service,
        )

    def _get_payload_generation_service(
        self,
        session_service: SessionService,
        second_llm_service: LLMOrchestrationService,
        tool_svc: ToolOrchestrationService,
        template_service: TemplateOrchestrationService,
        filesystem_utils: FileSystemUtils,
        git_utils: GitUtils,
    ) -> GeneratePayloadService:
        return GeneratePayloadService(
            session_service=session_service,
            second_llm_service=second_llm_service,
            tool_service=tool_svc,
            template_service=template_service,
            git_utils=git_utils,
            filesystem=filesystem_utils,
        )

    def _get_drift_service(
        self,
        validation_service: TerraformValidationService,
        validator_provider: ITerraformValidator,
        split_service: TaskSplitService,
    ) -> TerraformDriftService:
        return TerraformDriftService(
            validation_service=validation_service,
            validator_provider=validator_provider,
            split_service=split_service,
        )

    # --- Providers for Top-Level Use Cases ---
    # These providers compose the final use case objects.

    def _get_default_llm_service(
        self, tool_svc: ToolOrchestrationService
    ) -> LLMOrchestrationService:
        return self._get_llm_service(
            tool_svc,
            LLMProvider[system_config.llm.model],
            system_config.llm.temperature,
            LLMProvider[system_config.llm.small_model],
            system_config.llm.small_model_temperature,
        )

    def _wire_compliance(
        self,
        tool_registry: ToolRegistry,
        tool_svc: ToolOrchestrationService,
        llm_svc: LLMOrchestrationService,
        template_svc: TemplateOrchestrationService,
    ) -> None:
        if not system_config.compliance.enabled:
            return
        compliance_svc = ComplianceCheckService(
            tool_service=tool_svc,
            llm_service=llm_svc,
            template_service=template_svc,
        )
        tool_registry.set_compliance_checker(compliance_svc)

    def get_terraform_crud_handler(self) -> TerraformCRUDHandler:
        file_utils = self._get_file_utils()
        git_utils = self._get_git_utils(file_utils)
        tool_registry = self._get_tool_registry(file_utils, git_utils)
        tool_svc = self._get_tool_service(tool_registry)
        llm_svc = self._get_default_llm_service(tool_svc)
        session_svc = self._get_session_service(llm_svc)
        template_svc = self._get_template_service(llm_svc, tool_svc, file_utils)
        self._wire_compliance(tool_registry, tool_svc, llm_svc, template_svc)
        target_svc = self._get_terraform_target_service(tool_svc, llm_svc, template_svc)
        split_svc = self._get_terraform_split_service(tool_svc, llm_svc, template_svc)
        validator_prv = self._get_validator_provider(file_utils, session_svc)
        validation_svc = self._get_terraform_validation_service(
            git_utils=git_utils,
            template_service=template_svc,
            main_llm_service=llm_svc,
            session_service=session_svc,
            tool_service=tool_svc,
            target_service=target_svc,
            validator_provider=validator_prv,
        )
        setup_svc = self._get_project_setup_service(git_utils, file_utils)
        filter_svc = self._get_filter_request_service(llm_svc, tool_svc, template_svc)
        payload_svc = self._get_payload_generation_service(
            session_svc, llm_svc, tool_svc, template_svc, file_utils, git_utils
        )
        drift_svc = self._get_drift_service(validation_svc, validator_prv, split_svc)
        return TerraformCRUDHandler(
            validation_service=validation_svc,
            session_service=session_svc,
            template_service=template_svc,
            setup_service=setup_svc,
            payload_svc=payload_svc,
            filter_request_service=filter_svc,
            target_svc=target_svc,
            drift_svc=drift_svc,
            session_ctx=self.session_ctx,
        )

    def get_terraform_drift_handler(self) -> TerraformDriftHandler:
        file_utils = self._get_file_utils()
        git_utils = self._get_git_utils(file_utils)
        tool_registry = self._get_tool_registry(file_utils, git_utils)
        tool_svc = self._get_tool_service(tool_registry)
        llm_svc = self._get_default_llm_service(tool_svc)
        session_svc = self._get_session_service(llm_svc)
        template_svc = self._get_template_service(llm_svc, tool_svc, file_utils)
        self._wire_compliance(tool_registry, tool_svc, llm_svc, template_svc)
        target_svc = self._get_terraform_target_service(tool_svc, llm_svc, template_svc)
        split_svc = self._get_terraform_split_service(tool_svc, llm_svc, template_svc)
        validator_prv = self._get_validator_provider(file_utils, session_svc)
        validation_svc = self._get_terraform_validation_service(
            git_utils=git_utils,
            template_service=template_svc,
            main_llm_service=llm_svc,
            session_service=session_svc,
            tool_service=tool_svc,
            target_service=target_svc,
            validator_provider=validator_prv,
        )
        setup_svc = self._get_project_setup_service(git_utils, file_utils)
        filter_svc = self._get_filter_request_service(llm_svc, tool_svc, template_svc)
        payload_svc = self._get_payload_generation_service(
            session_svc, llm_svc, tool_svc, template_svc, file_utils, git_utils
        )
        drift_svc = self._get_drift_service(validation_svc, validator_prv, split_svc)
        return TerraformDriftHandler(
            validation_service=validation_svc,
            session_service=session_svc,
            template_service=template_svc,
            setup_service=setup_svc,
            payload_svc=payload_svc,
            filter_request_service=filter_svc,
            validator_provider=validator_prv,
            tool_service=tool_svc,
            target_service=target_svc,
            split_service=split_svc,
            drift_service=drift_svc,
            session_ctx=self.session_ctx,
        )

    def get_terraform_apply_handler(self) -> TerraformApplyHandler:
        file_utils = self._get_file_utils()
        git_utils = self._get_git_utils(file_utils)
        tool_registry = self._get_tool_registry(file_utils, git_utils)
        tool_svc = self._get_tool_service(tool_registry)
        llm_svc = self._get_default_llm_service(tool_svc)
        session_svc = self._get_session_service(llm_svc)
        template_svc = self._get_template_service(llm_svc, tool_svc, file_utils)
        payload_svc = self._get_payload_generation_service(
            session_svc, llm_svc, tool_svc, template_svc, file_utils, git_utils
        )
        # OSS reference has no apply impl; the route remains so the API
        # surface is stable but always errors with a clear message. Provide
        # your own IApplyInfrastructure to enable apply.
        apply_svc = ""
        return TerraformApplyHandler(
            apply_service=apply_svc,
            session_service=session_svc,
            template_service=template_svc,
            payload_svc=payload_svc,
            session_ctx=self.session_ctx,
        )

    def get_compliance_check_handler(self) -> ComplianceCheckHandler:
        file_utils = self._get_file_utils()
        git_utils = self._get_git_utils(file_utils)
        tool_registry = self._get_tool_registry(file_utils, git_utils)
        tool_svc = self._get_tool_service(tool_registry)
        llm_svc = self._get_default_llm_service(tool_svc)
        session_svc = self._get_session_service(llm_svc)
        template_svc = self._get_template_service(llm_svc, tool_svc, file_utils)
        compliance_svc = ComplianceCheckService(
            tool_service=tool_svc,
            llm_service=llm_svc,
            template_service=template_svc,
        )
        return ComplianceCheckHandler(
            compliance_service=compliance_svc,
            session_service=session_svc,
            template_service=template_svc,
            session_ctx=self.session_ctx,
        )
