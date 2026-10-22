# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

# pyright: reportAttributeAccessIssue=false

from src.domains.dto import PromptTemplateDTO
from src.domains.entities import History, SessionContext
from src.domains.services.database_service import DatabaseService
from src.domains.services.llm_service import LLMOrchestrationService
from src.domains.services.template_service import TemplateOrchestrationService
from src.shared.exceptions import ExceptionHandler
from src.shared.constants import PromptsLibrary, SessionStatus
from src.shared.logger import logging


class SessionService:
    """Session-scoped bookkeeping: statuses, rounds, and both histories."""

    def __init__(
        self,
        llm_service: LLMOrchestrationService,
        session_context: SessionContext,
        template_service: TemplateOrchestrationService,
    ):
        self.__llm_service = llm_service
        self.__ctx: SessionContext = session_context
        self.__template_svc = template_service

    async def update_status(
        self,
        msg: str,
        status: SessionStatus,
        prompt: PromptTemplateDTO | None = None,
        history: History | None = None,
    ) -> str:
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
        await DatabaseService.mark_session_status(
            session_id=self.__ctx.id,
            status=status,
            msg=msg,
            round_id=self.__ctx.round_id,
        )
        return msg

    async def next_round(self, q: str) -> None:
        rid = await DatabaseService.create_round(self.__ctx.id, q)
        self.__ctx.set_round(rid)

    async def save(self, query: str) -> None:
        try:
            reply = await self.__chat_reply(
                f"My request was: {query}\n",
                self.__ctx.history,
            )
            self.__ctx.chat_history.append_turn(query, reply)
        except ExceptionHandler:
            logging.warning(
                f"chat_reply failed for session {str(self.__ctx.id)[:4]}; "
                + "saving history without a chat turn"
            )
        await DatabaseService.update_history(self.__ctx)

    async def __chat_reply(self, query: str, history: History) -> str:
        """Infer the user-facing reply from the internal history alone."""
        return await self.__llm_service.generate_text(
            query=query,
            prompt=await self.__template_svc.render(PromptsLibrary.CHAT_REPLY),
            history=history,
        )
