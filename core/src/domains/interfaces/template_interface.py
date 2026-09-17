# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from abc import ABC, abstractmethod

from src.shared.constants import OperationType, ReportType, TargetGenerationMode


class ITemplate(ABC):
    @abstractmethod
    async def render_iac_generator(
        self,
        operation_type: OperationType,
        resources: list[str],
        abbreviations: list[str],
        include_forbidden_actions: bool,
        selected_ids: list[str] | None = None,
    ) -> str:
        pass

    @abstractmethod
    async def render_import_filter(
        self,
        unmanaged_ids: list[str],
        resources: list[str],
        abbreviations: list[str],
    ) -> str:
        pass

    @abstractmethod
    async def render_target_generator(
        self,
        mode: TargetGenerationMode,
        resources: list[str] | None = None,
    ) -> str:
        pass

    @abstractmethod
    async def render_report_generator(self, report_type: ReportType) -> str:
        pass

    @abstractmethod
    def render_pr_generator(self, operation_type: OperationType) -> str:
        pass

    @abstractmethod
    async def render_prompt_compositor(
        self,
        already_selected_templates: list[str] | None = None,
        already_selected_abbreviations: list[str] | None = None,
    ) -> str:
        pass

    @abstractmethod
    async def render_requests_filter(
        self,
        operation_type: OperationType,
    ) -> str:
        pass

    @abstractmethod
    def render_supervisor(self) -> str:
        pass

    @abstractmethod
    def render_task_splitter(self) -> str:
        pass

    @abstractmethod
    def render_filter_reconciliation(self) -> str:
        pass

    @abstractmethod
    def render_import_addresses(self) -> str:
        pass

    @abstractmethod
    def render_joker(self) -> str:
        pass

    @abstractmethod
    def render_status_update(self) -> str:
        pass

    @abstractmethod
    async def render_compliance_checker(
        self,
        resources: list[str],
        abbreviations: list[str],
    ) -> str:
        pass
