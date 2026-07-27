# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from typing import Literal
from abc import ABC, abstractmethod


class ITemplate(ABC):
    @abstractmethod
    async def render_iac_generator(
        self,
        resources: list[str],
        abbreviations: list[str],
        include_forbidden_actions: bool,
    ) -> str:
        pass

    @abstractmethod
    async def render_predictive_target_calculator(
        self,
        resources: list[str],
        abbreviations: list[str],
        include_forbidden_actions: bool,
    ) -> str:
        pass

    @abstractmethod
    def render_target_generator(self) -> str:
        pass

    @abstractmethod
    def render_report_generator(self, report_type: Literal["plan", "drift"]) -> str:
        pass

    @abstractmethod
    async def render_prompt_compositor(
        self,
        already_selected_templates: list[str] | None = None,
        already_selected_abbreviations: list[str] | None = None,
    ) -> str:
        pass

    @abstractmethod
    def render_domain_filter(self) -> str:
        pass

    @abstractmethod
    def render_supervisor(self) -> str:
        pass

    @abstractmethod
    def render_task_splitter(self) -> str:
        pass

    @abstractmethod
    def render_joker(self) -> str:
        pass

    @abstractmethod
    def render_status_update(self) -> str:
        pass

    @abstractmethod
    def render_task_acknowledge(self) -> str:
        pass

    @abstractmethod
    def render_iac_import(self) -> str:
        pass

    @abstractmethod
    async def render_compliance_checker(self, rules: str | None = None) -> str:
        pass
