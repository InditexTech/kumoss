# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from typing import Literal, override

from src.domains.interfaces.template_interface import ITemplate
from src.infrastructure.templates.jinja_env import jinja_environment


class CommonTemplateAdapter(ITemplate):
    _get_template = jinja_environment.get_template
    _core: str = "base_layouts/core/"
    _message: str = "base_layouts/messages/"

    def __init__(self, cwd: str):
        self._cwd = cwd

    @override
    def render_target_generator(self) -> str:
        t = self._get_template(self._core + "target_generator.jinja")
        return t.render()

    @override
    def render_report_generator(self, report_type: Literal["plan", "drift"]) -> str:
        t = self._get_template(self._core + "report_generator.jinja")
        return t.render(REPORT_TYPE=report_type)

    @override
    def render_domain_filter(self) -> str:
        t = self._get_template(self._core + "domain_filter.jinja")
        return t.render()

    @override
    def render_task_splitter(self) -> str:
        t = self._get_template(self._core + "task_splitter.jinja")
        return t.render()

    @override
    def render_joker(self) -> str:
        t = self._get_template(self._message + "joker.jinja")
        return t.render()

    @override
    def render_task_acknowledge(self) -> str:
        t = self._get_template(self._message + "task_acknowledge.jinja")
        return t.render()

    @override
    def render_status_update(self) -> str:
        t = self._get_template(self._message + "status_update.jinja")
        return t.render()

    @override
    def render_iac_import(self) -> str:
        t = self._get_template(self._core + "iac_import.jinja")
        return t.render()

    @override
    def render_compliance_checker(self, rules: str) -> str:
        t = self._get_template(self._core + "compliance_checker.jinja")
        return t.render(RULES=rules)

    @override
    async def render_iac_generator(
        self,
        resources: list[str],
        abbreviations: list[str],
        include_forbidden_actions: bool,
    ) -> str:
        raise NotImplementedError()

    @override
    async def render_prompt_compositor(
        self,
        already_selected_templates: list[str] | None = None,
        already_selected_abbreviations: list[str] | None = None,
    ) -> str:
        raise NotImplementedError()

    @override
    async def render_predictive_target_calculator(
        self,
        resources: list[str],
        abbreviations: list[str],
        include_forbidden_actions: bool,
    ) -> str:
        raise NotImplementedError()

    @override
    def render_supervisor(self) -> str:
        raise NotImplementedError()
