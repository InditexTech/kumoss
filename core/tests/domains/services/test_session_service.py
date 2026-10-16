# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

# pyright: basic, reportArgumentType=false

"""``save()`` is the only writer of the user-facing conversation.

Every use case calls it from a ``finally``, so it runs whether the round
completed or raised.
"""

import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from src.domains.dto import PromptTemplateDTO
from src.domains.entities import SessionContext
from src.domains.services.session_service import SessionService
from src.shared.constants import (
    OperationType,
    PromptsLibrary,
    SessionStatus,
    TerraformProvider,
)

CHAT_PROMPT = PromptTemplateDTO(type=PromptsLibrary.CHAT_REPLY, prompt="be brief")


def _ctx(history: list[dict[str, str]] | None = None) -> SessionContext:
    return SessionContext(
        id=uuid4(),
        user_id="user@example.com",
        round_id=1,
        repo_uri="https://example.com/foo.git",
        scope_id="sub-123",
        terraform_prv=TerraformProvider.AZURE,
        branch_name="Nebula/x",
        iac_path="infra",
        operation_type=OperationType.GENERATE,
        history=history,
        chat_history=[],
    )


class _ServiceBase(unittest.IsolatedAsyncioTestCase):
    """A service wired to doubles, with every DatabaseService call stubbed."""

    async def asyncSetUp(self):
        self.ctx = _ctx()
        self.llm = AsyncMock()
        self.llm.generate_text.return_value = "Done: the plan adds one vnet."
        self.templates = AsyncMock()
        self.templates.render.return_value = CHAT_PROMPT
        self.svc = SessionService(
            llm_service=self.llm,
            session_context=self.ctx,
            template_service=self.templates,
        )
        patcher = patch(
            "src.domains.services.session_service.DatabaseService",
            new=AsyncMock(),
        )
        self.database = patcher.start()
        self.addCleanup(patcher.stop)
        self.database.create_round.return_value = 2

    def chat(self) -> list[dict[str, str]]:
        return self.ctx.chat_history.serialize()


class TestChatTurnIsWrittenOnlyBySave(_ServiceBase):
    async def test_completed_round_stores_the_inferred_reply(self):
        await self.svc.next_round("add a vnet")
        await self.svc.update_status("generating", SessionStatus.GENERATING)
        await self.svc.update_status("all good", SessionStatus.COMPLETED)
        await self.svc.save()

        self.assertEqual(
            self.chat(),
            [{"user": "add a vnet", "assistant": "Done: the plan adds one vnet."}],
        )
        self.database.update_history.assert_awaited_once_with(self.ctx)

    async def test_reply_is_inferred_from_the_internal_history_alone(self):
        self.ctx.history.append_turn("add a vnet", "<raw llm summary>")
        await self.svc.next_round("add a vnet")
        await self.svc.save()

        kwargs = self.llm.generate_text.await_args.kwargs
        self.assertEqual(kwargs["query"], "add a vnet")
        self.assertIs(kwargs["prompt"], CHAT_PROMPT)
        self.assertIs(kwargs["history"], self.ctx.history)
        self.templates.render.assert_awaited_once_with(PromptsLibrary.CHAT_REPLY)

    async def test_next_round_writes_nothing_on_its_own(self):
        await self.svc.next_round("add a vnet")
        self.assertEqual(self.chat(), [])
        self.llm.generate_text.assert_not_awaited()

    async def test_status_updates_write_nothing_on_their_own(self):
        await self.svc.next_round("add a vnet")
        await self.svc.update_status("working", SessionStatus.GENERATING)
        self.assertEqual(self.chat(), [])

    async def test_each_round_adds_exactly_one_turn(self):
        for query in ("add a vnet", "and a subnet"):
            await self.svc.next_round(query)
            await self.svc.save()

        self.assertEqual(
            [turn["user"] for turn in self.chat()], ["add a vnet", "and a subnet"]
        )


class TestSaveEdgeCases(_ServiceBase):
    async def test_an_empty_reply_skips_the_turn(self):
        self.llm.generate_text.return_value = ""
        await self.svc.next_round("add a vnet")
        await self.svc.save()

        self.assertEqual(self.chat(), [])
        self.database.update_history.assert_awaited_once_with(self.ctx)

    async def test_a_round_that_raised_still_gets_its_turn(self):
        # Use cases call save() from a finally, so the failure path reaches
        # here with the round open and the status already marked FAILED.
        await self.svc.next_round("add a vnet")
        await self.svc.update_status("boom", SessionStatus.FAILED)
        await self.svc.save()

        self.assertEqual(
            self.chat(),
            [{"user": "add a vnet", "assistant": "Done: the plan adds one vnet."}],
        )
