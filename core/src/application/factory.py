# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

# Domain layer imports
from pathlib import Path
from typing import final

from src.application.use_cases.terraform_compliance_check_handler import (
    TerraformComplianceCheckHandler,
)
from src.domains.entities.session import SessionContext
from src.domains.interfaces import ILLMProvider, ITerraform
from src.domains.interfaces.filesystem_interface import IFileSystem
from src.domains.interfaces.git_interface import IGit
from src.domains.services import (
    ComplianceCheckService,
    IacRootDetectionService,
    LLMOrchestrationService,
    SessionService,
    TemplateOrchestrationService,
    TerraformTargetService,
    TerraformValidationService,
    ToolOrchestrationService,
    TaskSplitService,
    ArtifactStorageService,
)

# Infrastructure layer imports
from src.infrastructure.storage import default_object_storage
from src.infrastructure.tools import ToolRegistryWorkspace, ToolRegistryStatic
from src.infrastructure.filesystem import (
    FileSystemUtils,
    GitUtils,
    IacRootDetector,
    WorkspaceService,
)
from src.infrastructure.templates.template_adapter import TemplateAdapter
from src.infrastructure.llm.factory import LLMFactory
from src.infrastructure.terraform.factory import TerraformFactory

# Application layer imports
from src.application.services import (
    RequestsFilterService,
    TerraformDriftService,
    PullRequestService,
    ReportService,
)
from src.application.use_cases import (
    ComplianceCheckHandler,
    TerraformCRUDHandler,
    TerraformDriftHandler,
    TerraformApplyHandler,
)

# Shared imports
from src.shared.config import system_config


@final
class ApplicationFactory:
    def __init__(
        self,
        session_ctx: SessionContext,
    ):
        self.__ctx: SessionContext = session_ctx

    # --- Providers for Infrastructure Components ---
    # These providers create the concrete implementations for the utils

    def _get_file_utils(self, path: Path | None = None) -> FileSystemUtils:
        return FileSystemUtils(root=path or self.__ctx.call_dir)

    @staticmethod
    def get_git_utils(
        repo_uri: str,
        path: Path | None = None,
    ) -> GitUtils:
        return GitUtils(
            uri=repo_uri,
            git_provider=system_config.git.provider,
            cwd=path,
        )

    # --- Providers for Domain Services ---
    # These providers construct the domain services, injecting infrastructure components.

    @staticmethod
    def get_llm_adapter(
        model_id: str, max_tokens: int, temperature: float
    ) -> ILLMProvider:
        return LLMFactory(
            model_id=model_id,
            max_tokens=max_tokens,
            temperature=temperature,
        ).get()

    @staticmethod
    def _get_llm_service(
        main_llm: str,
        main_temp: float,
        main_max_tokens: int,
        small_llm: str,
        small_temp: float,
        small_max_tokens: int,
        tool_service: ToolOrchestrationService | None = None,
    ) -> LLMOrchestrationService:
        return LLMOrchestrationService(
            main_llm_provider=ApplicationFactory.get_llm_adapter(
                model_id=main_llm,
                max_tokens=main_max_tokens,
                temperature=main_temp,
            ),
            small_llm_provider=ApplicationFactory.get_llm_adapter(
                model_id=small_llm,
                max_tokens=small_max_tokens,
                temperature=small_temp,
            ),
            tool_service=tool_service,
        )

    def _get_tool_registry_workspace(
        self, file_utils: IFileSystem, git_utils: IGit
    ) -> ToolRegistryWorkspace:
        return ToolRegistryWorkspace(
            filesystem=file_utils,
            git=git_utils,
            llm=ApplicationFactory.get_llm_adapter(
                model_id=system_config.llm.small_model,
                max_tokens=system_config.llm.small_model_max_output_tokens,
                temperature=0.5,
            ),
        )

    def _get_tool_service_workspace(
        self, file_utils: IFileSystem, git_utils: IGit
    ) -> ToolOrchestrationService:
        return ToolOrchestrationService(
            tool_registry=self._get_tool_registry_workspace(file_utils, git_utils)
        )

    def _get_tool_service_static(self) -> ToolOrchestrationService:
        return ToolOrchestrationService(
            tool_registry=ToolRegistryStatic(
                llm=ApplicationFactory.get_llm_adapter(
                    model_id=system_config.llm.small_model,
                    max_tokens=system_config.llm.small_model_max_output_tokens,
                    temperature=0.5,
                ),
            )
        )

    def _get_session_service(self, second_llm_service: LLMOrchestrationService):
        return SessionService(
            llm_service=second_llm_service, session_context=self.__ctx
        )

    def _get_template_service(
        self,
        call_dir: Path,
        llm_service: LLMOrchestrationService,
        tool_service: ToolOrchestrationService,
    ):
        template_adapter = TemplateAdapter(
            template_provider=self.__ctx.terraform_prv,
            cwd=call_dir.as_posix(),
        )
        return TemplateOrchestrationService(
            templates=template_adapter,
            llm_service=llm_service,
            tool_service=tool_service,
        )

    @staticmethod
    def get_iac_root_detection_service() -> IacRootDetectionService:
        return IacRootDetectionService(
            workspace=WorkspaceService(),
            detector=IacRootDetector(),
        )

    def _get_artifact_storage_service(self) -> ArtifactStorageService:
        return ArtifactStorageService(default_object_storage())

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

    def _get_terraform_provider(
        self,
        project_root: Path,
    ) -> ITerraform:
        return TerraformFactory(project_root).get()

    def _get_terraform_validation_service(
        self,
        git_utils: GitUtils,
        file_utils: FileSystemUtils,
        session_service: SessionService,
        template_service: TemplateOrchestrationService,
        main_llm_service: LLMOrchestrationService,
        tool_service: ToolOrchestrationService,
        artifact_service: ArtifactStorageService,
        compliance_service: ComplianceCheckService | None = None,
    ) -> TerraformValidationService:
        return TerraformValidationService(
            git=git_utils,
            files=file_utils,
            session_service=session_service,
            template_service=template_service,
            llm_service=main_llm_service,
            tool_orchestration_service=tool_service,
            artifact_service=artifact_service,
            compliance_service=compliance_service,
        )

    # --- Providers for Application Building Blocks ---

    def get_pull_request_service(self) -> PullRequestService:
        git_utils = self.get_git_utils(self.__ctx.repo_uri)
        tool_svc = self._get_tool_service_static()
        llm_svc = self._get_default_llm_service(tool_svc)
        template_svc = self._get_template_service(
            system_config.paths.upload_folder, llm_svc, tool_svc
        )
        return PullRequestService(
            session_ctx=self.__ctx,
            git_utils=git_utils,
            llm_service=llm_svc,
            tool_service=tool_svc,
            template_service=template_svc,
        )

    def _get_requests_filter_service(
        self,
        session_service: SessionService,
        second_llm_service: LLMOrchestrationService,
        tool_service: ToolOrchestrationService,
        template_service: TemplateOrchestrationService,
    ):
        return RequestsFilterService(
            session_service=session_service,
            second_llm_service=second_llm_service,
            tool_service=tool_service,
            template_service=template_service,
        )

    def _get_report_service(
        self,
        second_llm_service: LLMOrchestrationService,
        tool_service: ToolOrchestrationService,
        template_service: TemplateOrchestrationService,
        session_service: SessionService,
        artifact_service: ArtifactStorageService,
    ) -> ReportService:
        return ReportService(
            second_llm_service=second_llm_service,
            tool_service=tool_service,
            template_service=template_service,
            session_service=session_service,
            artifact_service=artifact_service,
        )

    def _get_drift_service(
        self,
        validation_service: TerraformValidationService,
        validator_provider: ITerraform,
        split_service: TaskSplitService,
        artifact_service: ArtifactStorageService,
    ) -> TerraformDriftService:
        return TerraformDriftService(
            session_context=self.__ctx,
            validation_service=validation_service,
            validator_provider=validator_provider,
            split_service=split_service,
            artifact_service=artifact_service,
        )

    # --- Providers for Top-Level Use Cases ---
    # These providers compose the final use case objects.

    def _get_default_llm_service(
        self, tool_svc: ToolOrchestrationService | None = None
    ) -> LLMOrchestrationService:
        return self._get_llm_service(
            main_llm=system_config.llm.model,
            main_max_tokens=system_config.llm.max_output_tokens,
            main_temp=system_config.llm.temperature,
            small_llm=system_config.llm.small_model,
            small_temp=system_config.llm.small_model_temperature,
            small_max_tokens=system_config.llm.small_model_max_output_tokens,
            tool_service=tool_svc,
        )

    def _get_compliance_service(
        self,
        tool_svc: ToolOrchestrationService,
        llm_svc: LLMOrchestrationService,
        template_svc: TemplateOrchestrationService,
    ) -> ComplianceCheckService | None:
        return ComplianceCheckService(
            tool_service=tool_svc,
            llm_service=llm_svc,
            template_service=template_svc,
        )

    def get_terraform_crud_handler(self) -> TerraformCRUDHandler:
        file_utils = self._get_file_utils()
        artifact_svc = self._get_artifact_storage_service()
        git_utils = self.get_git_utils(self.__ctx.repo_uri, file_utils.project_root)
        tool_svc = self._get_tool_service_workspace(file_utils, git_utils)
        llm_svc = self._get_default_llm_service(tool_svc)
        session_svc = self._get_session_service(llm_svc)
        template_svc = self._get_template_service(
            file_utils.project_root, llm_svc, tool_svc
        )
        target_svc = self._get_terraform_target_service(tool_svc, llm_svc, template_svc)
        report_svc = self._get_report_service(
            llm_svc, tool_svc, template_svc, session_svc, artifact_svc
        )
        split_svc = self._get_terraform_split_service(tool_svc, llm_svc, template_svc)
        validator_prv = self._get_terraform_provider(file_utils.project_root)
        compliance_svc = self._get_compliance_service(tool_svc, llm_svc, template_svc)
        validation_svc = self._get_terraform_validation_service(
            git_utils=git_utils,
            file_utils=file_utils,
            session_service=session_svc,
            template_service=template_svc,
            main_llm_service=llm_svc,
            tool_service=tool_svc,
            artifact_service=artifact_svc,
            compliance_service=compliance_svc,
        )
        filter_svc = self._get_requests_filter_service(
            session_service=session_svc,
            second_llm_service=llm_svc,
            tool_service=tool_svc,
            template_service=template_svc,
        )
        drift_svc = self._get_drift_service(
            validation_service=validation_svc,
            validator_provider=validator_prv,
            split_service=split_svc,
            artifact_service=artifact_svc,
        )
        return TerraformCRUDHandler(
            session_ctx=self.__ctx,
            session_service=session_svc,
            terraform_service=validator_prv,
            validation_service=validation_svc,
            template_service=template_svc,
            requests_filter_service=filter_svc,
            report_service=report_svc,
            target_service=target_svc,
            drift_service=drift_svc,
        )

    def get_terraform_drift_handler(self) -> TerraformDriftHandler:
        file_utils = self._get_file_utils()
        artifact_svc = self._get_artifact_storage_service()
        git_utils = self.get_git_utils(self.__ctx.repo_uri, file_utils.project_root)
        tool_svc = self._get_tool_service_workspace(file_utils, git_utils)
        llm_svc = self._get_default_llm_service(tool_svc)
        session_svc = self._get_session_service(llm_svc)
        template_svc = self._get_template_service(
            file_utils.project_root, llm_svc, tool_svc
        )
        target_svc = self._get_terraform_target_service(tool_svc, llm_svc, template_svc)
        report_svc = self._get_report_service(
            llm_svc, tool_svc, template_svc, session_svc, artifact_svc
        )
        split_svc = self._get_terraform_split_service(tool_svc, llm_svc, template_svc)
        validator_prv = self._get_terraform_provider(file_utils.project_root)
        validation_svc = self._get_terraform_validation_service(
            git_utils=git_utils,
            file_utils=file_utils,
            session_service=session_svc,
            template_service=template_svc,
            main_llm_service=llm_svc,
            tool_service=tool_svc,
            artifact_service=artifact_svc,
        )
        filter_svc = self._get_requests_filter_service(
            session_service=session_svc,
            second_llm_service=llm_svc,
            tool_service=tool_svc,
            template_service=template_svc,
        )
        drift_svc = self._get_drift_service(
            validation_service=validation_svc,
            validator_provider=validator_prv,
            split_service=split_svc,
            artifact_service=artifact_svc,
        )
        return TerraformDriftHandler(
            session_ctx=self.__ctx,
            session_service=session_svc,
            terraform_service=validator_prv,
            validation_service=validation_svc,
            template_service=template_svc,
            requests_filter_service=filter_svc,
            report_service=report_svc,
            target_service=target_svc,
            drift_service=drift_svc,
        )

    def get_terraform_apply_handler(self) -> TerraformApplyHandler:
        file_utils = self._get_file_utils()
        git_utils = self.get_git_utils(self.__ctx.repo_uri, file_utils.project_root)
        artifact_svc = self._get_artifact_storage_service()
        tool_svc = self._get_tool_service_workspace(file_utils, git_utils)
        llm_svc = self._get_default_llm_service(tool_svc)
        session_svc = self._get_session_service(llm_svc)
        template_svc = self._get_template_service(
            call_dir=file_utils.project_root,
            llm_service=llm_svc,
            tool_service=tool_svc,
        )
        target_svc = self._get_terraform_target_service(tool_svc, llm_svc, template_svc)
        report_svc = self._get_report_service(
            llm_svc, tool_svc, template_svc, session_svc, artifact_svc
        )
        terraform_svc = self._get_terraform_provider(file_utils.project_root)
        validation_svc = self._get_terraform_validation_service(
            git_utils=git_utils,
            file_utils=file_utils,
            session_service=session_svc,
            template_service=template_svc,
            main_llm_service=llm_svc,
            tool_service=tool_svc,
            artifact_service=artifact_svc,
        )
        return TerraformApplyHandler(
            terraform_service=terraform_svc,
            validation_service=validation_svc,
            target_service=target_svc,
            session_service=session_svc,
            report_service=report_svc,
            template_service=template_svc,
            session_ctx=self.__ctx,
        )

    def get_compliance_check_handler(
        self,
        mode: str = "plan_vs_core",
        phoenix_prompt_name: str | None = None,
    ) -> TerraformComplianceCheckHandler:
        file_utils = self._get_file_utils()
        git_utils = self.get_git_utils(self.__ctx.repo_uri, file_utils.project_root)
        tool_svc = self._get_tool_service_workspace(file_utils, git_utils)
        llm_svc = self._get_default_llm_service(tool_svc)
        session_svc = self._get_session_service(llm_svc)
        template_svc = self._get_template_service(
            file_utils.project_root, llm_svc, tool_svc
        )
        compliance_svc = ComplianceCheckService(
            tool_service=tool_svc,
            llm_service=llm_svc,
            template_service=template_svc,
        )
        return ComplianceCheckHandler(
            compliance_service=compliance_svc,
            session_service=session_svc,
            template_service=template_svc,
            session_ctx=self.__ctx,
            mode=mode,
            phoenix_prompt_name=phoenix_prompt_name,
        )
