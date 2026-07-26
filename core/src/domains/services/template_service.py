# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import inspect
from typing import Any

from src.domains.dto import PromptTemplateDTO, ToolResultDTO
from src.domains.entities.history import History
from src.domains.exceptions import TemplateRendererNotFound, TemplateRendererArgErr
from src.domains.interfaces.template_interface import ITemplate
from src.domains.services.llm_service import LLMOrchestrationService
from src.domains.services.tool_service import ToolOrchestrationService
from src.shared.constants import PromptsLibrary, ToolContext
from src.shared.logger import logging


class TemplateOrchestrationService:
    def __init__(
        self,
        templates: ITemplate,
        llm_service: LLMOrchestrationService,
        tool_service: ToolOrchestrationService,
    ):
        self.__templates = templates
        self.__llm_svc = llm_service
        self.__tool_svc = tool_service
        self.__template_renderers: dict[str, Any] = {}
        self.__register_renderers()

    def __register_renderers(self):
        self.__template_renderers = {
            # core
            "domain_filter": self.__templates.render_domain_filter,
            "task_splitter": self.__templates.render_task_splitter,
            "prompt_compositor": self.__templates.render_prompt_compositor,
            "iac_generator": self.__templates.render_iac_generator,
            "iac_import": self.__templates.render_iac_import,
            "predictive_target_calculator": self.__templates.render_predictive_target_calculator,
            "target_generator": self.__templates.render_target_generator,
            "report_generator": self.__templates.render_report_generator,
            "supervisor": self.__templates.render_supervisor,
            "compliance_checker": self.__templates.render_compliance_checker,
            # messages
            "joker": self.__templates.render_joker,
            "status_update": self.__templates.render_status_update,
            "task_acknowledge": self.__templates.render_task_acknowledge,
        }

    async def render(self, prompt: PromptsLibrary, **kwargs: Any) -> PromptTemplateDTO:
        if prompt.value not in self.__template_renderers:
            raise TemplateRendererNotFound(
                message=f"Template renderer {prompt.value} not found.",
                error_code=404,
            )
        try:
            renderer = self.__template_renderers[prompt.value]
            if inspect.iscoroutinefunction(renderer):
                if kwargs:
                    plain_prompt = await renderer(**kwargs)
                else:
                    plain_prompt = await self.__template_renderers[prompt.value]()
            else:
                if kwargs:
                    plain_prompt = renderer(**kwargs)
                else:
                    plain_prompt = self.__template_renderers[prompt.value]()
            return PromptTemplateDTO(
                type=prompt,
                prompt=plain_prompt,
            )
        except TypeError as e:
            raise TemplateRendererArgErr(
                message=f"wrong arguments for {prompt}: {str(e)}",
                error_code=400,
            )

    async def compose_template(
        self,
        query: str,
        history: History,
    ) -> tuple[list[str], list[str]]:
        """
        Runs a two-pass prompt compositor chain and returns a tuple with a list of
        related_templates, and a list of related abbreviatnios based on the user query

        Pass 1: Infer templates and abbreviations from the user query.
        Pass 2: Re-run compositor with already-selected templates and abbreviations
                to discover related/dependent items.
        Merge: Deduplicate templates and abbreviations from both passes.

        :param query: User query
        :param history: Conversation history
        :return: Fully rendered PromptTemplateDTO ready for the next LLM call
        """
        compositor_tools = self.__tool_svc.get_available_tools(
            [ToolContext.PROMPT_COMPOSITOR]
        )

        # Pass 1: infer templates and abbreviations
        first_pass: ToolResultDTO = await self.__llm_svc.generate(
            query=query,
            tools=compositor_tools,
            prompt=await self.render(PromptsLibrary.PROMPT_COMPOSITOR),
            history=history,
        )
        templates: list[str] = first_pass.result["templates"]
        abbreviations: list[str] = first_pass.result["abbreviations"]

        # Pass 2: discover related/dependent templates and abbreviations
        second_pass: ToolResultDTO = await self.__llm_svc.generate(
            query=query,
            tools=self.__tool_svc.get_available_tools([ToolContext.PROMPT_COMPOSITOR]),
            prompt=await self.render(
                PromptsLibrary.PROMPT_COMPOSITOR,
                already_selected_templates=templates,
                already_selected_abbreviations=abbreviations,
            ),
            history=history,
        )
        related_templates: list[str] = second_pass.result["templates"]
        related_abbreviations: list[str] = second_pass.result["abbreviations"]

        # Merge and deduplicate
        merged_templates: list[str] = list(set(templates + related_templates))
        merged_abbreviations: list[str] = list(
            set(abbreviations + related_abbreviations)
        )
        logging.debug(f"Prompt compositor merged templates: {merged_templates} ")
        logging.debug(
            f"Prompt compositor merged abbreviations: {merged_abbreviations} "
        )

        return (merged_templates, merged_abbreviations)
