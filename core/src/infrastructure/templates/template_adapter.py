# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from typing import Literal, override

from src.domains.interfaces.template_interface import ITemplate
from src.infrastructure.templates._fetcher import remote_fetcher
from src.infrastructure.templates.jinja_env import jinja_environment
from src.infrastructure.exceptions import (
    PhoenixPromptFetchError,
    RemoteTemplateFetcherError,
)
from src.shared.config import system_config
from src.shared.logger import logging
from src.shared.constants import TerraformProvider


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
    async def render_iac_generator(
        self,
        resources: list[str],
        abbreviations: list[str],
        include_forbidden_actions: bool,
    ) -> str:
        concrete_implementations: list[str] = (
            [f"This is the convention for resource naming: {abbreviations}"]
            if abbreviations
            else []
        )
        try:
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
            concrete_implementations.extend(
                await self._get_resources_templates(resources)
            )
        except PhoenixPromptFetchError as e:
            logging.error(f"Error template couldn't be fetched. Error: {e.message}")
            raise RemoteTemplateFetcherError(
                message=f"Error fetching remote template. {e.message}",
                error_code=502,
            )
        base_template = self._get_template(self._core + "iac_generator.jinja")
        return base_template.render(
            GENERAL_TERRAFORM_GUIDELINES=terraform_guidelines,
            FORBIDDEN_ACTIONS=forbidden_actions,
            RESOURCE_CREATION=resource_creation,
            NETWORKING=networking,
            PERMISSIONS=permissions,
            CONCRETE_IMPLEMENTATION="\n".join(concrete_implementations),
            CWD=self._cwd,
        )

    @override
    async def render_predictive_target_calculator(
        self,
        resources: list[str],
        abbreviations: list[str],
        include_forbidden_actions: bool,
    ) -> str:
        concrete_implementations: list[str] = (
            [f"This is the convention for resource naming: {abbreviations}"]
            if abbreviations
            else []
        )
        try:
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
            concrete_implementations.extend(
                await self._get_resources_templates(resources)
            )
        except PhoenixPromptFetchError as e:
            logging.error(f"Error template couldn't be fetched. Error: {e.message}")
            raise RemoteTemplateFetcherError(
                message=f"Error fetching remote template. {e.message}",
                error_code=502,
            )
        base_template = self._get_template(
            self._core + "predictive_target_calculator.jinja"
        )
        return base_template.render(
            GENERAL_TERRAFORM_GUIDELINES=terraform_guidelines,
            FORBIDDEN_ACTIONS=forbidden_actions,
            RESOURCE_CREATION=resource_creation,
            NETWORKING=networking,
            PERMISSIONS=permissions,
            CONCRETE_IMPLEMENTATION="\n".join(concrete_implementations),
            CWD=self._cwd,
        )

    @override
    async def render_prompt_compositor(
        self,
        already_selected_templates: list[str] | None = None,
        already_selected_abbreviations: list[str] | None = None,
    ) -> str:
        try:
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
        except PhoenixPromptFetchError as e:
            logging.error(f"Error template couldn't be fetched. Error: {e.message}")
            raise RemoteTemplateFetcherError(
                message=f"Error fetching remote template. {e.message}",
                error_code=502,
            )

        templates_content: list[str] = await self._get_resources_templates(
            already_selected_templates or []
        )
        templates_and_content: dict = (
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
            try:
                rendered_resources.append(
                    await remote_fetcher.fetch(
                        prompt_name=r,
                        scope=self._scope,
                        type="resources",
                        tag=system_config.environment,
                    )
                )
            except PhoenixPromptFetchError as e:
                logging.error(f"Error template couldn't be fetched. Error: {e.message}")
                continue
        return rendered_resources

    @override
    def render_supervisor(self) -> str:
        raise NotImplementedError()
