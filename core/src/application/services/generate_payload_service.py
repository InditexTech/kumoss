# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from typing import Any, Literal

from src.application.exceptions import ReportGenerationError
from src.domains.entities import History
from src.domains.interfaces import IFileSystem, IGit
from src.domains.services import (
    LLMOrchestrationService,
    SessionService,
    ToolOrchestrationService,
    TemplateOrchestrationService,
)
from src.domains.dto import (
    TerraformDriftReport,
    TerraformValidationDTO,
    TerraformPlanReport,
    TerraformApplyReport,
    ToolResultDTO,
)
from src.domains.services.database_service import DatabaseService
from src.shared.constants import SessionStatus, ToolContext, PromptsLibrary


class GeneratePayloadService:
    def __init__(
        self,
        session_service: SessionService,
        second_llm_service: LLMOrchestrationService,
        tool_service: ToolOrchestrationService,
        template_service: TemplateOrchestrationService,
        git_utils: IGit,
        filesystem: IFileSystem,
    ):
        self.__session_svc = session_service
        self.__second_llm_svc = second_llm_service
        self.__tool_svc = tool_service
        self.__template_svc = template_service
        self.__git = git_utils
        self.__filesystem = filesystem

    async def generate(
        self,
        response: str,
        command: Any,
        history: History,
        branch: str,
        validation: TerraformValidationDTO | None = None,
    ):
        return
        history.append_turn(
            user_msg=command.q,
            assistant_msg="Task successfully finished"
            if validation and validation.validation
            else "The task could not be completed",
        )
        await self.__session_svc.update_status(
            msg="Infrastructure successfully validated. Generating report.",
            status=SessionStatus.REPORT,
        )

        formatted_response = (
            response
            if not validation
            else await self.__format_response(validation.validation, history)
        )
        report = (
            await self.__generate_report(
                query=validation.terraform_plan,
                report_type="plan",
            )
            if validation and validation.validation
            else None
        )

        apply_allowed = True
        if report and any(
            detail.action in ("delete", "recreate")
            for detail in report.detailed_changes
        ):
            apply_allowed = False
            await DatabaseService.set_apply_allowed(
                str(self.__session_svc.context.id), False
            )

        await self.__session_svc.set_payload(
            query=command.q,
            response=formatted_response,
            history=history,
            branch=branch,
            validation=validation.validation if validation else False,
            project=self.__get_project_name(),
            environment=command.environment,
            cloud=command.cloud,
            terraform_plan=validation.terraform_plan if validation else None,
            terraform_targets=validation.terraform_targets if validation else None,
            terraform_report=report,
            apply_allowed=apply_allowed,
        )
        await self.__session_svc.update_status(
            msg="Report generated",
            status=SessionStatus.COMPLETED,
        )

    async def generate_drift(
        self,
        command: Any,
        validation: TerraformValidationDTO,
        branch: str,
    ):
        summaries = self.__session_svc.summaries
        summaries.append(
            f"This is the last state of the drift: {validation.terraform_plan}"
        )
        if validation.validation:
            summaries.append(
                "As all the operation has been addressed, please, set the final status as complete."
            )
        if not validation.validation:
            summaries.append(
                "The following operations could not be completed, please, "
                + f"set the final status report as 'Partial':\n{validation.feedback}"
            )
        await self.__session_svc.update_status(
            msg=f"Drift resolved{' partially' if not validation.validation else ''}. Generating report.",
            status=SessionStatus.REPORT,
        )

        await self.__session_svc.set_payload(
            query="",
            response=await self.__format_response(True),
            history=History(),
            branch=branch,
            validation=True,  # Always true bc report has to be shown
            project=self.__get_project_name(),
            environment=command.environment,
            cloud=command.cloud,
            terraform_plan=validation.terraform_plan,
            terraform_targets=validation.terraform_targets,
            terraform_report=await self.__generate_report(
                query=str(summaries),
                report_type="drift",
            ),
        )
        await self.__session_svc.update_status(
            msg="Drift report generated",
            status=SessionStatus.COMPLETED,
        )

    async def generate_apply(
        self,
        response: str,
        command: Any,
        validation: bool,
        run_id: str,
        apply_output: str | None = None,
    ):
        terraform_apply_report = None
        if apply_output:
            await self.__session_svc.update_status(
                msg="Generating report",
                status=SessionStatus.REPORT,
            )

            terraform_apply_report = await self.__generate_report(
                query=apply_output,
                report_type="apply",
            )

        await self.__session_svc.set_payload(
            query="Terraform Apply",
            response=response,
            history=History(),
            branch=await self.__git.get_default_branch(),
            validation=validation,
            project=self.__get_project_name(),
            environment=command.environment,
            cloud=command.cloud,
            terraform_plan=apply_output,
            terraform_report=terraform_apply_report,
        )
        await self.__session_svc.update_status(
            msg="Report generated" if apply_output else "Apply completed",
            status=SessionStatus.COMPLETED,
        )

    async def __format_response(
        self, validation: bool, history: History | None = None
    ) -> str:
        if validation:
            return self.__format_files_response(
                file_names=await self.__git.get_changed_files("AM"),
            )

        return await self.__second_llm_svc.generate_text(
            query="Provide feedback for what went wrong and how could be solved",
            prompt=await self.__template_svc.render(PromptsLibrary.STATUS_UPDATE),
            history=history,
        )

    def __format_files_response(self, file_names: list[str]) -> str:
        """This function returns the content of the input file names wrapped around
        xml tags with the name of the file
        :param file_names: The list of files names
        :return: A string containing all the formatted content
        """
        output: str = ""
        for file in file_names:
            output += f"""
            <{file}>
            {self.__filesystem.read_file(file)}
            </{file}>"
            """
        return output

    def __get_project_name(self) -> str:
        return self.__filesystem.project_root.name

    async def __generate_report(
        self,
        query: str,
        report_type: Literal["plan", "drift", "apply"],
    ) -> TerraformPlanReport | TerraformDriftReport | TerraformApplyReport | None:
        tool_index = {"plan": 0, "drift": 1, "apply": 2}.get(report_type, 0)

        response: ToolResultDTO = await self.__second_llm_svc.generate(
            query=query,
            tools=[
                self.__tool_svc.get_available_tools([ToolContext.REPORT_GENERATOR])[
                    tool_index
                ]
            ],
            prompt=await self.__template_svc.render(
                PromptsLibrary.REPORT_GENERATOR,
                report_type=report_type,
            ),
        )
        if not response.success:
            raise ReportGenerationError(
                f"report '{report_type}' generation error.", 500
            )
        return response.result
