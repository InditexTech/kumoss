# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

# pyright: reportAttributeAccessIssue=false
from uuid import UUID

from src.domains.entities import Session, get_session, History
from src.domains.services.llm_service import LLMOrchestrationService
from src.domains.dto import (
    PromptTemplateDTO,
    SessionPayloadDTO,
    TerraformDriftReport,
    TerraformPlanReport,
)
from src.domains.exceptions import SessionNotInitializeError, SessionNotFound
from src.shared.constants import SessionStatus
from src.shared.logger import logging


class SessionService:
    def __init__(
        self,
        llm_service: LLMOrchestrationService,
    ):
        self.__session: Session = None
        self.__summaries: list[str] = []
        self.__llm_service = llm_service

    @property
    def session(self) -> Session:
        return self.__session

    @property
    def summaries(self) -> list[str]:
        return self.__summaries

    def append_summary(self, summ: str):
        self.__summaries.append(summ)

    def create_session(self, id: UUID):
        self.__session = Session(
            id=id,
            status=SessionStatus.STARTED,
        )

    def set_validation_id(self, id: str):
        """Set the validation ID (pipeline build ID for example)
        :param id: the validator ID
        :return: None
        """
        self.__session.set_validation_id(id)

    async def update_status(
        self,
        msg: str,
        status: SessionStatus,
        prompt: PromptTemplateDTO | None = None,
        history: History | None = None,
    ) -> None:
        """Update the session with a new status and a message.
        Optionally, use an LLM to generate the msg.

        :param status: New session status
        :param msg: New message
        :param prompt: System prompt for session message inference
        :param history: Conversation history obj for inference
        :return: None
        """
        logging.debug(
            f"Session id '{self.__session.id[:4]}' has been updated to {status.name}"
        )
        self.__check_session()
        if prompt:
            msg: str = await self.__llm_service.generate_text(
                query=msg,
                prompt=prompt,
                history=history,
            )
        self.__session.set_status(status=status, message=msg)

    async def set_payload(
        self,
        query: str,
        response: str,
        history: History,
        validation: bool,
        project: str,
        environment: str,
        cloud: str,
        branch: str,
        terraform_plan: str | None = None,
        terraform_targets: list[str] | None = None,
        terraform_report: TerraformPlanReport | TerraformDriftReport | None = None,
        pipeline_url: str | None = None,
        apply_allowed: bool = True,
    ):
        self.__check_session()
        self.__session.set_payload(
            SessionPayloadDTO(
                response=response,
                main_history=History([{"user": query, "assistant": response}]),
                full_history=history.serialize(),
                validation=validation,
                project=project,
                environment=environment,
                cloud=cloud,
                branch_name=branch,
                id=self.__session.id,
                terraform_plan=terraform_plan,
                terraform_targets=terraform_targets,
                terraform_report=terraform_report,
                pipeline_url=pipeline_url,
                apply_allowed=apply_allowed,
            )
        )

    def __check_session(self):
        if not self.__session:
            raise SessionNotInitializeError(
                message="Error session is not initialized",
                error_code=500,
            )

    @staticmethod
    def get_session(id: UUID) -> Session:
        session = get_session(id)
        if not session:
            raise SessionNotFound(
                message=f"Session with id {str(id)} doesn't exist.",
                error_code=404,
            )
        return session
