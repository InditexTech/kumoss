# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

# pyright: reportAttributeAccessIssue=false
from typing import cast

from src.domains.entities import SessionContext, History
from src.domains.services.database_service import DatabaseService
from src.domains.services.llm_service import LLMOrchestrationService
from src.domains.dto import (
    PromptTemplateDTO,
    TerraformDriftReport,
    TerraformPlanReport,
)
from src.shared.constants import SessionStatus
from src.shared.logger import logging


class SessionService:
    def __init__(
        self,
        llm_service: LLMOrchestrationService,
        session_context: SessionContext,
    ):
        self.__llm_service = llm_service
        self.__ctx: SessionContext = session_context

    @property
    def session(self) -> SessionContext:
        return self.__ctx

    async def update_status(
        self,
        msg: str,
        status: SessionStatus,
        prompt: PromptTemplateDTO | None = None,
        history: History | None = None,
    ) -> None:
        """Update the session with a new status and a message.
        Optionally, use an LLM to generate the msg.

        :param msg: New message
        :param status: New session status
        :param prompt: System prompt for session message inference
        :param history: Conversation history obj for inference
        :return: None
        """
        logging.debug(
            f"Session id '{str(self.__ctx.id)[:4]}' has been updated to {status.name}"
        )
        if prompt:
            msg = await self.__llm_service.generate_text(
                query=msg,
                prompt=prompt,
                history=history,
            )
        await DatabaseService.mark_session_status(self.__ctx.id, status, cast(str, msg))

    async def save(self) -> None:
        await DatabaseService.update_session(self.__ctx)

    # FIXME: stale
    async def set_payload(
        self,
        files: str,
        history: History,
        terraform_report: TerraformPlanReport | TerraformDriftReport | None = None,
        apply_allowed: bool = True,
    ):
        return
        # self.__ctx.set_payload(
        #     SessionPayloadDTO(
        #         files=files,
        #         history=history.serialize(),
        #         terraform_report=terraform_report,
        #         apply_allowed=apply_allowed,
        #     )
        # )
