# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from typing import final, override

from src.infrastructure.templates._common import CommonTemplateAdapter
from src.infrastructure.templates._fetcher import remote_fetcher
from src.infrastructure.templates.jinja_env import jinja_environment
from src.infrastructure.exceptions import (
    PhoenixPromptFetchError,
    RemoteTemplateFetcherError,
)
from src.shared.config import system_config
from src.shared.logger import logging


@final
class OCITemplateAdapter(CommonTemplateAdapter):
    _get_template = jinja_environment.get_template

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
            resource_creation = await self.__fetch_oci_guidelines("resource_creation")
            forbidden_actions = (
                await self.__fetch_oci_guidelines("forbidden_actions")
                if include_forbidden_actions
                else None
            )
            networking = await self.__fetch_oci_guidelines("networking")
            permissions = await self.__fetch_oci_guidelines("permissions")
            concrete_implementations.extend(
                await self.__get_resources_templates(resources)
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
            resource_creation = await self.__fetch_oci_guidelines("resource_creation")
            forbidden_actions = (
                await self.__fetch_oci_guidelines("forbidden_actions")
                if include_forbidden_actions
                else None
            )
            networking = await self.__fetch_oci_guidelines("networking")
            permissions = await self.__fetch_oci_guidelines("permissions")
            concrete_implementations.extend(
                await self.__get_resources_templates(resources)
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

    async def __get_resources_templates(self, resources: list[str]) -> list[str]:
        rendered_resources: list[str] = []
        for r in resources:
            try:
                rendered_resources.append(
                    await remote_fetcher.fetch(
                        prompt_name=r,
                        scope="oci",
                        type="resources",
                        tag=system_config.environment,
                    )
                )
            except PhoenixPromptFetchError as e:
                logging.error(f"Error template couldn't be fetched. Error: {e.message}")
                continue
        return rendered_resources

    @override
    async def render_prompt_compositor(
        self,
        already_selected_templates: list[str] | None = None,
        already_selected_abbreviations: list[str] | None = None,
    ):
        try:
            abbr = await remote_fetcher.fetch(
                prompt_name="abbreviations",
                scope="oci",
                type="guidelines",
                tag=system_config.environment,
            )
            resources = await remote_fetcher.fetch(
                prompt_name="resources_list",
                scope="oci",
                type="guidelines",
                tag=system_config.environment,
            )
        except PhoenixPromptFetchError as e:
            logging.error(f"Error template couldn't be fetched. Error: {e.message}")
            raise RemoteTemplateFetcherError(
                message=f"Error fetching remote template. {e.message}",
                error_code=502,
            )

        try:
            templates_content: list[str] = (
                await self.__get_resources_templates(already_selected_templates) or []
            )
        except PhoenixPromptFetchError as e:
            logging.error(
                f"Error template couldn't be fetched to read content. Error: {e.message}"
            )
            raise RemoteTemplateFetcherError(
                message=f"Error fetching remote template. {e.message}",
                error_code=502,
            )

        t = self._get_template(self._core + "prompt_compositor.jinja")
        return t.render(
            AVAILABLE_TEMPLATES_LIST=resources,
            AVAILABLE_ABBREVIATIONS_LIST=abbr,
            ALREADY_SELECTED_TEMPLATES=already_selected_templates,
            ALREADY_SELECTED_TEMPLATES_CONTENT=templates_content,
            ALREADY_SELECTED_ABBREVIATIONS=already_selected_abbreviations,
        )

    async def __fetch_oci_guidelines(self, name: str) -> str:
        return await remote_fetcher.fetch(
            prompt_name=name,
            scope="oci",
            type="guidelines",
            tag=system_config.environment,
        )
