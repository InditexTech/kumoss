# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import unittest
from uuid import uuid4

from httpx import ASGITransport, AsyncClient

from src.main import app
from src.domains.services.database_service import DatabaseService
from src.domains.services.user_service import UserService
from src.infrastructure.database.database import db
from src.infrastructure.database.models import Base
from src.infrastructure.redis import redis_client
from src.shared.constants import (
    OperationType,
    ReportType,
    SessionStatus,
    TerraformProvider,
)


class TestSessionsApi(unittest.IsolatedAsyncioTestCase):
    """Contract tests for GET /v1/sessions and GET /v1/sessions/{id}."""

    async def asyncSetUp(self):
        await db.initialize()
        await redis_client.initialize()
        async with db.session_manager.engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        # Auth is disabled in the test config, so every request acts as
        # the dev identity; the listed sessions must belong to it.
        self.user = await UserService.resolve()
        self.username = self.user.email
        self.sid = uuid4()
        _ = await DatabaseService.create_session(
            session_id=self.sid,
            user_pk=self.user.id,
            operation=OperationType.GENERATE,
            repo_uri="https://example.com/foo.git",
            terraform_prv=TerraformProvider.AZURE,
            scope_id="sub-123",
            branch_name="Nebula/x",
            query="create a resource group",
            iac_path="infra",
        )
        self.client = AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        )

    async def asyncTearDown(self):
        await self.client.aclose()
        await redis_client.close()
        await db.close()

    async def test_list_matches_contract(self):
        resp = await self.client.get("/v1/sessions")
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["total"], 1)
        self.assertEqual(body["page"], 1)
        self.assertEqual(body["total_pages"], 1)
        item = body["items"][0]
        self.assertEqual(item["uuid"], str(self.sid))
        self.assertEqual(item["username"], self.username)
        self.assertEqual(item["operation"], "generate")
        self.assertEqual(item["provider"], "azure")
        self.assertEqual(item["first_query"], "create a resource group")
        self.assertEqual(item["workspace_uri"], "https://example.com/foo.git")
        self.assertEqual(item["current_status"], "started")
        self.assertFalse(item["in_flight"])
        self.assertFalse(item["is_blocked"])

    async def test_detail_aggregates_rounds_and_artifacts(self):
        round_id = await DatabaseService.create_round(self.sid, "add a vnet")
        await DatabaseService.mark_session_status(
            self.sid, SessionStatus.GENERATING, "round 2", round_id=round_id
        )
        _ = await DatabaseService.add_report(
            round_id=round_id,
            report_type=ReportType.GENERATE,
            uri="https://blob.example.com/report.json",
            content_type="application/json",
            file_size_bytes=512,
        )
        _ = await DatabaseService.add_terraform_plan(
            round_id=round_id,
            targets=["azurerm_resource_group.main"],
            uri="https://blob.example.com/plan.txt",
            content_type="text/plain",
            file_size_bytes=2048,
        )
        _ = await DatabaseService.add_code_change(
            round_id=round_id,
            file_name="main.tf",
            uri="https://blob.example.com/main.tf",
            content_type="text/plain",
            file_size_bytes=128,
        )
        _ = await DatabaseService.add_compliance_check(
            round_id=round_id,
            passed=False,
            uri="https://blob.example.com/check.json",
            content_type="application/json",
            file_size_bytes=256,
        )
        await DatabaseService.add_pull_request(
            self.sid, "https://github.com/org/repo/pull/42", 42
        )

        resp = await self.client.get(f"/v1/sessions/{self.sid}")
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()

        self.assertEqual(body["uuid"], str(self.sid))
        self.assertEqual(body["operation"], "generate")
        self.assertEqual(body["scope_id"], "sub-123")
        self.assertEqual(body["workspace"]["branch"], "Nebula/x")
        self.assertEqual(body["workspace"]["root_path"], "infra")
        # Pull requests live inside their round, not at session level.
        self.assertNotIn("pull_request", body)
        self.assertNotIn("pull_requests", body)
        self.assertEqual(body["current_status"], "generating")
        # Session-level timeline spans all rounds.
        self.assertEqual(
            [s["status"] for s in body["statuses"]], ["started", "generating"]
        )
        # History is opt-in via ?include_history=true; null by default.
        self.assertIsNone(body["history"])

        self.assertEqual(len(body["rounds"]), 2)
        first = body["rounds"][0]
        self.assertEqual(first["number"], 1)
        self.assertEqual([s["status"] for s in first["statuses"]], ["started"])
        self.assertEqual(first["pull_requests"], [])
        rnd = body["rounds"][1]
        self.assertEqual(rnd["number"], 2)
        self.assertEqual([s["status"] for s in rnd["statuses"]], ["generating"])
        # URLs are presigned by the object-storage singleton; the stored
        # key must be embedded in the signed URL.
        self.assertIn("report.json", rnd["report"]["url"])
        self.assertEqual(rnd["plan"]["targets"], ["azurerm_resource_group.main"])
        self.assertEqual(rnd["code_changes"][0]["file_name"], "main.tf")
        self.assertEqual(rnd["code_changes"][0]["file_size_bytes"], 128)
        self.assertIn("check.json", rnd["compliance"]["url"])
        self.assertFalse(rnd["compliance"]["passed"])
        # Rounds without a check (the compliance checker is optional)
        # expose it as null.
        self.assertIsNone(first["compliance"])
        self.assertEqual(
            rnd["pull_requests"],
            [
                {
                    "provider": "GITHUB",
                    "url": "https://github.com/org/repo/pull/42",
                    "number": 42,
                }
            ],
        )

    async def test_detail_include_history(self):
        ctx = await DatabaseService.get_session_context(self.sid)
        ctx.history.append_turn("create a resource group", "done: rg-main")
        await DatabaseService.update_history(ctx)

        resp = await self.client.get(
            f"/v1/sessions/{self.sid}", params={"include_history": "true"}
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(
            resp.json()["history"],
            [{"user": "create a resource group", "assistant": "done: rg-main"}],
        )

        # Default stays history-less.
        resp = await self.client.get(f"/v1/sessions/{self.sid}")
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertIsNone(resp.json()["history"])

    async def test_detail_unknown_session_is_404(self):
        resp = await self.client.get(f"/v1/sessions/{uuid4()}")
        self.assertEqual(resp.status_code, 404, resp.text)

    async def test_list_filters(self):
        await DatabaseService.mark_session_status(
            self.sid, SessionStatus.GENERATING, "working"
        )

        async def fetch(**params: str) -> int:
            resp = await self.client.get("/v1/sessions", params=params)
            self.assertEqual(resp.status_code, 200, resp.text)
            return resp.json()["total"]

        self.assertEqual(await fetch(operation="generate"), 1)
        self.assertEqual(await fetch(operation="drift"), 0)
        self.assertEqual(await fetch(status="generating"), 1)
        self.assertEqual(await fetch(status="failed"), 0)
        self.assertEqual(await fetch(search="resource group"), 1)
        self.assertEqual(await fetch(search="foo.git"), 1)
        self.assertEqual(await fetch(search=str(self.sid)), 1)
        self.assertEqual(await fetch(search=str(self.sid)[:8]), 1)
        self.assertEqual(await fetch(search="no-match-xyz"), 0)
