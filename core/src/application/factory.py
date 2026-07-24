# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

# Domain layer imports
from pathlib import Path
from typing import final

from src.domains.entities.session import SessionContext
from src.domains.interfaces import ILLMProvider, ITerraformValidator
from src.domains.interfaces.filesystem_interface import IFileSystem
from src.domains.interfaces.git_interface import IGit
from src.domains.services import (
    IacRootDetectionService,
    LLMOrchestrationService,
    SessionService,
    TemplateOrchestrationService,
    TerraformTargetService,
    TerraformValidationService,
    ToolOrchestrationService,
)

# Infrastructure layer imports
from src.domains.services.task_split_service import TaskSplitService
from src.infrastructure.external.gemini_web_search import GeminiWebSearch
from src.infrastructure.tools.tool_registry import ToolRegistry
from src.infrastructure.filesystem import (
    FileSystemUtils,
    GitUtils,
    IacRootDetector,
    WorkspaceService,
)
from src.infrastructure.templates.template_adapter import TemplateAdapter
from src.infrastructure.llm.factory import LLMFactory
from src.infrastructure.validators.factory import ValidatorFactory

# Application layer imports
from src.application.services import (
    FilterRequestService,
    GeneratePayloadService,
    TerraformDriftService,
    PullRequestService,
)
from src.application.use_cases import (
    TerraformCRUDHandler,
    TerraformDriftHandler,
    TerraformApplyHandler,
)

# Shared imports
from src.shared.constants import (
    TerraformProvider,
    LLMProvider,
)
from src.shared.config import system_config


@final
class ApplicationFactory:
    def __init__(
        self,
        session_ctx: SessionContext | None = None,
    ):
        self.__ctx: SessionContext | None = session_ctx

    # --- Providers for Infrastructure Components ---
    # These providers create the concrete implementations for the utils

    def _get_file_utils(self, path: Path | None = None) -> FileSystemUtils:
        assert path is not None or (
            self.__ctx is not None and self.__ctx.iac_path is not None
        )
        return FileSystemUtils(root=self.__ctx.call_dir if self.__ctx else path)

    def _get_git_utils(self, path: Path) -> GitUtils:
        return GitUtils(
            git_provider=system_config.git.provider,
            cwd=path,
        )

    # --- Providers for Domain Services ---
    # These providers construct the domain services, injecting infrastructure components.

    @staticmethod
    def get_llm_adapter(provider: LLMProvider, temperature: float) -> ILLMProvider:
        return LLMFactory(
            provider=provider,
            temperature=temperature,
        ).get()

    @staticmethod
    def _get_llm_service(
        main_llm: LLMProvider,
        main_temp: float,
        small_llm: LLMProvider,
        small_temp: float,
        tool_service: ToolOrchestrationService | None = None,
    ) -> LLMOrchestrationService:
        return LLMOrchestrationService(
            main_llm_provider=ApplicationFactory.get_llm_adapter(
                provider=main_llm,
                temperature=main_temp,
            ),
            small_llm_provider=ApplicationFactory.get_llm_adapter(
                provider=small_llm,
                temperature=small_temp,
            ),
            tool_service=tool_service,
        )

    def _get_tool_service(
        self, file_utils: IFileSystem, git_utils: IGit
    ) -> ToolOrchestrationService:
        return ToolOrchestrationService(
            tool_registry=ToolRegistry(
                filesystem=file_utils,
                git=git_utils,
                web_search=GeminiWebSearch(
                    gemini=self.get_llm_adapter(system_config.llm.small_model, 0.5)
                ),
            )
        )

    def _get_session_service(self, second_llm_service: LLMOrchestrationService):
        assert self.__ctx is not None
        return SessionService(
            llm_service=second_llm_service, session_context=self.__ctx
        )

    def _get_template_service(
        self,
        llm_service: LLMOrchestrationService,
        tool_service: ToolOrchestrationService,
        file_utils: IFileSystem,
        provider: TerraformProvider | None = None,
    ):
        assert provider is not None or (
            self.__ctx is not None and self.__ctx.terraform_prv is not None
        )
        template_adapter = TemplateAdapter(
            template_provider=self.__ctx.terraform_prv if self.__ctx else provider,
            cwd=str(file_utils.project_root),
        )
        return TemplateOrchestrationService(
            templates=template_adapter,
            llm_service=llm_service,
            tool_service=tool_service,
        )

    def get_iac_root_detection_service(self) -> IacRootDetectionService:
        return IacRootDetectionService(
            workspace=WorkspaceService(),
            detector=IacRootDetector(),
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

    def get_pull_request_service(self) -> PullRequestService:
        file_utils = self._get_file_utils()
        git_utils = self._get_git_utils(file_utils.project_root)
        tool_svc = self._get_tool_service(file_utils, git_utils)
        llm_svc = self._get_default_llm_service(tool_svc)
        return PullRequestService(
            git_utils=git_utils,
            llm_service=llm_svc,
        )

    def _get_filter_request_service(
        self,
        session_service: SessionService,
        second_llm_service: LLMOrchestrationService,
        tool_svc: ToolOrchestrationService,
        template_service: TemplateOrchestrationService,
    ):
        return FilterRequestService(
            session_service=session_service,
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
        self, tool_svc: ToolOrchestrationService | None = None
    ) -> LLMOrchestrationService:
        return self._get_llm_service(
            main_llm=system_config.llm.model,
            main_temp=system_config.llm.temperature,
            small_llm=system_config.llm.small_model,
            small_temp=system_config.llm.small_model_temperature,
            tool_service=tool_svc,
        )

    def get_terraform_crud_handler(self) -> TerraformCRUDHandler:
        file_utils = self._get_file_utils()
        git_utils = self._get_git_utils(file_utils.project_root)
        tool_svc = self._get_tool_service(file_utils, git_utils)
        llm_svc = self._get_default_llm_service(tool_svc)
        session_svc = self._get_session_service(llm_svc)
        template_svc = self._get_template_service(llm_svc, tool_svc, file_utils)
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
        filter_svc = self._get_filter_request_service(
            session_svc, llm_svc, tool_svc, template_svc
        )
        payload_svc = self._get_payload_generation_service(
            session_svc, llm_svc, tool_svc, template_svc, file_utils, git_utils
        )
        drift_svc = self._get_drift_service(validation_svc, validator_prv, split_svc)
        return TerraformCRUDHandler(
            validation_service=validation_svc,
            session_service=session_svc,
            template_service=template_svc,
            payload_svc=payload_svc,
            filter_request_service=filter_svc,
            target_svc=target_svc,
            drift_svc=drift_svc,
            session_ctx=self.__ctx,
        )

    def get_terraform_drift_handler(self) -> TerraformDriftHandler:
        file_utils = self._get_file_utils()
        git_utils = self._get_git_utils(file_utils.project_root)
        tool_svc = self._get_tool_service(file_utils, git_utils)
        llm_svc = self._get_default_llm_service(tool_svc)
        session_svc = self._get_session_service(llm_svc)
        template_svc = self._get_template_service(llm_svc, tool_svc, file_utils)
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
        filter_svc = self._get_filter_request_service(
            session_svc, llm_svc, tool_svc, template_svc
        )
        payload_svc = self._get_payload_generation_service(
            session_svc, llm_svc, tool_svc, template_svc, file_utils, git_utils
        )
        drift_svc = self._get_drift_service(validation_svc, validator_prv, split_svc)
        return TerraformDriftHandler(
            validation_service=validation_svc,
            session_service=session_svc,
            template_service=template_svc,
            payload_svc=payload_svc,
            filter_request_service=filter_svc,
            validator_provider=validator_prv,
            tool_service=tool_svc,
            target_service=target_svc,
            split_service=split_svc,
            drift_service=drift_svc,
            session_ctx=self.__ctx,
        )

    def get_terraform_apply_handler(self) -> TerraformApplyHandler:
        file_utils = self._get_file_utils()
        git_utils = self._get_git_utils(file_utils.project_root)
        tool_svc = self._get_tool_service(file_utils, git_utils)
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
            session_ctx=self.__ctx,
        )
