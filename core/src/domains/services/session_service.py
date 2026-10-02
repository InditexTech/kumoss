# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

# pyright: reportAttributeAccessIssue=false
from typing import cast

from src.domains.dto import PromptTemplateDTO
from src.domains.entities import History, SessionContext
from src.domains.services.database_service import DatabaseService
from src.domains.services.llm_service import LLMOrchestrationService
from src.domains.services.template_service import TemplateOrchestrationService
from src.shared.constants import PromptsLibrary, SessionStatus
from src.shared.logger import logging


class SessionService:
    """Session-scoped bookkeeping: statuses, rounds, and both histories.

    Holds the current round's state so that ``save()`` can write the
    round's user-facing chat turn without the use cases knowing about it.
    """

    def __init__(
        self,
        llm_service: LLMOrchestrationService,
        session_context: SessionContext,
        template_service: TemplateOrchestrationService,
    ):
        self.__llm_service = llm_service
        self.__ctx: SessionContext = session_context
        self.__template_svc = template_service
        # Round state. ``None`` means this service never opened a round,
        # so there is no chat turn to write.
        self.__round_query: str | None = None
        self.__rejected: bool = False

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
        # A rejected round's chat reply is the rationale the requests filter
        # already wrote to the internal history — never an inference.
        if status is SessionStatus.UNCOMPLETED:
            self.__rejected = True
        if prompt:
            msg = await self.__llm_service.generate_text(
                query=msg,
                prompt=prompt,
                history=history,
            )
        await DatabaseService.mark_session_status(
            session_id=self.__ctx.id,
            status=status,
            msg=cast(str, msg),
            round_id=self.__ctx.round_id,
        )
        return msg

    async def next_round(self, q: str) -> None:
        rid = await DatabaseService.create_round(self.__ctx.id, q)
        self.__ctx.set_round(rid)
        self.__round_query = q
        self.__rejected = False

    async def save(self) -> None:
        """Persist both histories at the end of a round.

        Called from every use case's ``finally``, so it runs whether the
        round completed or raised.
        """
        await self.__append_chat_turn()
        await DatabaseService.update_history(self.__ctx)

    async def __append_chat_turn(self) -> None:
        """Record the round's user-facing turn.

        Never raises: ``update_history`` must run even when no reply can
        be produced. An empty reply is passed to ``append_turn`` as-is,
        which logs and skips the turn.
        """
        if self.__round_query is None:
            return
        reply: str = ""
        try:
            reply = (
                str(self.__ctx.history.get_last_turn().assistant)
                if self.__rejected
                else await self.__chat_reply(self.__round_query)
            )
        except Exception as e:
            logging.warning(
                f"Chat reply failed on session '{str(self.__ctx.id)[:4]}': {e}"
            )
        self.__ctx.chat_history.append_turn(self.__round_query, reply)

    async def __chat_reply(self, query: str) -> str:
        """Infer the user-facing reply from the internal history alone."""
        return await self.__llm_service.generate_text(
            query=f'Write the chat reply for the latest round history. The user asked: "{query}"',
            prompt=await self.__template_svc.render(PromptsLibrary.CHAT_REPLY),
            history=self.__ctx.history,
        )
