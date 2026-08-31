# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from typing import final, override

from src.domains.interfaces.template_interface import ITemplate
from src.infrastructure.templates._fetcher import remote_fetcher
from src.infrastructure.templates.jinja_env import jinja_environment
from src.shared.config import system_config
from src.shared.constants import OperationType, ReportType, TerraformProvider


@final
class TemplateAdapter(ITemplate):
    _get_template = jinja_environment.get_template
    _core: str = "base_layouts/core/"
    _message: str = "base_layouts/messages/"
    _scope: str

    def __init__(self, template_provider: TerraformProvider, cwd: str):
        self._scope = template_provider.value
        self._cwd = cwd

    @override
    def render_target_generator(self) -> str:
        t = self._get_template(self._core + "target_generator.jinja")
        return t.render()

    @override
    def render_report_generator(self, report_type: ReportType) -> str:
        t = self._get_template(self._core + "report_generator.jinja")
        return t.render(REPORT_TYPE=report_type.value)

    @override
    def render_pr_generator(self, operation_type: OperationType) -> str:
        t = self._get_template(self._core + "pr_generator.jinja")
        return t.render(OPERATION_TYPE=operation_type.value)

    @override
    async def render_requests_filter(
        self,
        resources: list[str],
        abbreviations: list[str],
        include_forbidden_actions: bool,
        operation_type: OperationType,
    ) -> str:
        context = await self._compose_conventions_context(
            resources, abbreviations, include_forbidden_actions
        )
        requests_guidelines: str = await remote_fetcher.fetch(
            prompt_name="requests",
            scope="general",
            type="guidelines",
            tag=system_config.environment,
        )
        t = self._get_template(self._core + "requests_filter.jinja")
        return t.render(
            **context,
            REQUESTS_GUIDELINES=requests_guidelines,
            OPERATION_TYPE=operation_type.value,
        )

    @override
    def render_task_splitter(self) -> str:
        t = self._get_template(self._core + "task_splitter.jinja")
        return t.render()

    @override
    def render_joker(self) -> str:
        t = self._get_template(self._message + "joker.jinja")
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
    async def render_iac_generator(
        self,
        resources: list[str],
        abbreviations: list[str],
        include_forbidden_actions: bool,
    ) -> str:
        context = await self._compose_conventions_context(
            resources, abbreviations, include_forbidden_actions
        )
        base_template = self._get_template(self._core + "iac_generator.jinja")
        return base_template.render(**context)

    @override
    async def render_predictive_target_calculator(
        self,
        resources: list[str],
    ) -> str:
        guidelines = await remote_fetcher.fetch(
            prompt_name="predictive_targets",
            scope="general",
            type="guidelines",
            tag=system_config.environment,
        )
        t = self._get_template(self._core + "predictive_target_calculator.jinja")
        return t.render(
            RELEVANT_TEMPLATES=resources,
            PREDICTIVE_TARGETS_GUIDELINES=guidelines,
            CWD=self._cwd,
        )

    @override
    async def render_prompt_compositor(
        self,
        already_selected_templates: list[str] | None = None,
        already_selected_abbreviations: list[str] | None = None,
    ) -> str:
        abbr = await remote_fetcher.fetch(
            prompt_name="abbreviations",
            scope=self._scope,
            type="guidelines",
            tag=system_config.environment,
        )
        resources = await remote_fetcher.fetch(
            prompt_name="resources_list",
            scope=self._scope,
            type="guidelines",
            tag=system_config.environment,
        )

        templates_content: list[str] = await self._get_resources_templates(
            already_selected_templates or []
        )
        templates_and_content: dict[str, str] = (
            dict(zip(already_selected_templates, templates_content))
            if already_selected_templates and templates_content
            else dict.fromkeys(already_selected_templates or [], "")
        )

        t = self._get_template(self._core + "prompt_compositor.jinja")
        return t.render(
            AVAILABLE_TEMPLATES_LIST=resources,
            AVAILABLE_ABBREVIATIONS_LIST=abbr,
            ALREADY_SELECTED_TEMPLATES=templates_and_content,
            ALREADY_SELECTED_ABBREVIATIONS=already_selected_abbreviations,
        )

    @override
    async def render_compliance_checker(
        self,
        resources: list[str],
        abbreviations: list[str],
    ) -> str:
        context = await self._compose_conventions_context(
            resources, abbreviations, True
        )
        context["REPORT_COMPLIANCE_RULES"] = await remote_fetcher.fetch(
            prompt_name="report",
            scope="general",
            type="compliance",
            tag=system_config.environment,
        )
        t = self._get_template(self._core + "compliance_checker.jinja")
        return t.render(**context)

    async def _compose_conventions_context(
        self,
        resources: list[str],
        abbreviations: list[str],
        include_forbidden_actions: bool,
    ) -> dict[str, str | None]:
        concrete_implementations: list[str] = (
            [f"This is the convention for resource naming: {abbreviations}"]
            if abbreviations
            else []
        )
        terraform_guidelines: str = await remote_fetcher.fetch(
            prompt_name="terraform",
            scope="general",
            type="guidelines",
            tag=system_config.environment,
        )
        resource_creation = await self._fetch_guidelines("resource_creation")
        forbidden_actions = (
            await self._fetch_guidelines("forbidden_actions")
            if include_forbidden_actions
            else None
        )
        networking = await self._fetch_guidelines("networking")
        permissions = await self._fetch_guidelines("permissions")
        concrete_implementations.extend(await self._get_resources_templates(resources))
        return {
            "GENERAL_TERRAFORM_GUIDELINES": terraform_guidelines,
            "FORBIDDEN_ACTIONS": forbidden_actions,
            "RESOURCE_CREATION": resource_creation,
            "NETWORKING": networking,
            "PERMISSIONS": permissions,
            "CONCRETE_IMPLEMENTATION": "\n".join(concrete_implementations),
            "CWD": self._cwd,
        }

    async def _fetch_guidelines(self, name: str) -> str:
        return await remote_fetcher.fetch(
            prompt_name=name,
            scope=self._scope,
            type="guidelines",
            tag=system_config.environment,
        )

    async def _get_resources_templates(self, resources: list[str]) -> list[str]:
        rendered_resources: list[str] = []
        for r in resources:
            rendered_resources.append(
                await remote_fetcher.fetch(
                    prompt_name=r,
                    scope=self._scope,
                    type="resources",
                    tag=system_config.environment,
                )
            )
        return rendered_resources

    @override
    def render_supervisor(self) -> str:
        raise NotImplementedError()
