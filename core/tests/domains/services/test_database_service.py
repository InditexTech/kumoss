# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""DatabaseService tests focused on the Redis cache staying truthful.

Every mutation is paired with a read to prove the cached copy is fresh:
the write paths write-through (they never delete), so a stale cache here
would mean a broken write-through, not an unlucky TTL.
"""

import unittest
from uuid import uuid4

from src.domains.exceptions import (
    LastStatusError,
    SessionConflict,
    SessionTerminal,
)
from src.domains.services.database_service import DatabaseService
from src.infrastructure.database.database import db
from src.infrastructure.database.models import Base, PullRequest, Round, Session, User
from src.infrastructure.redis import redis_client
from src.shared.constants import (
    GitProviderName,
    OperationType,
    ReportType,
    SessionStatus,
    TerraformProvider,
)


class _SessionBase(unittest.IsolatedAsyncioTestCase):
    """One fresh session per test, with DB wiped and unique cache keys."""

    async def asyncSetUp(self):
        await db.initialize()
        await redis_client.initialize()
        async with db.session_manager.engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        # Unique email per run so stale Redis mappings never leak in.
        self.username = f"user-{uuid4().hex[:8]}@example.com"
        user = await db.create(
            User,
            issuer="urn:test",
            subject=f"sub-{uuid4().hex[:8]}",
            email=self.username,
        )
        self.user_pk = user.id
        self.sid = uuid4()
        _ = await DatabaseService.create_session(
            session_id=self.sid,
            user_pk=self.user_pk,
            operation=OperationType.GENERATE,
            repo_uri="https://example.com/foo.git",
            terraform_prv=TerraformProvider.AZURE,
            scope_id="sub-123",
            branch_name="Kumoss/x",
            query="create a resource group",
            iac_path="infra",
        )

    async def asyncTearDown(self):
        await redis_client.close()
        await db.close()


class TestLastStatusFreshness(_SessionBase):
    async def test_unknown_session_raises(self):
        with self.assertRaises(LastStatusError):
            _ = await DatabaseService.get_last_status(uuid4())

    async def test_create_session_opens_with_started(self):
        status = await DatabaseService.get_last_status(self.sid)
        self.assertEqual(status.status, SessionStatus.STARTED)

    async def test_reads_track_every_write(self):
        await DatabaseService.mark_session_status(
            self.sid, SessionStatus.GENERATING, "working"
        )
        status = await DatabaseService.get_last_status(self.sid)
        self.assertEqual(status.status, SessionStatus.GENERATING)

        # The previous read cached GENERATING; the next write must win.
        await DatabaseService.mark_completed(self.sid, "done")
        status = await DatabaseService.get_last_status(self.sid)
        self.assertEqual(status.status, SessionStatus.COMPLETED)
        self.assertEqual(status.msg, "done")

    async def test_summary_reflects_latest_status(self):
        summary = await DatabaseService.get_session_summary(self.sid)
        self.assertEqual(summary.current_status, SessionStatus.STARTED)

        await DatabaseService.mark_failed(self.sid, "boom")
        summary = await DatabaseService.get_session_summary(self.sid)
        self.assertEqual(summary.current_status, SessionStatus.FAILED)


class TestSessionContextFreshness(_SessionBase):
    async def test_round_trips_through_the_cache(self):
        ctx = await DatabaseService.get_session_context(self.sid)
        self.assertEqual(ctx.id, self.sid)
        self.assertEqual(ctx.user_id, self.username)
        self.assertEqual(ctx.repo_uri, "https://example.com/foo.git")
        self.assertEqual(ctx.scope_id, "sub-123")
        self.assertEqual(ctx.terraform_prv, TerraformProvider.AZURE)
        self.assertEqual(ctx.branch_name, "Kumoss/x")
        self.assertEqual(ctx.iac_path, "infra")
        self.assertEqual(len(ctx.history), 0)

        # Second read is served from the cache and must agree.
        cached = await DatabaseService.get_session_context(self.sid)
        self.assertEqual(cached.repo_uri, ctx.repo_uri)
        self.assertEqual(cached.history.serialize(), ctx.history.serialize())

    async def test_update_history_refreshes_cached_history(self):
        ctx = await DatabaseService.get_session_context(self.sid)
        ctx.history.append_turn(user_msg="hi", assistant_msg="hello")
        await DatabaseService.update_history(ctx)

        again = await DatabaseService.get_session_context(self.sid)
        self.assertEqual(
            again.history.serialize(), [{"user": "hi", "assistant": "hello"}]
        )

    async def test_update_history_touches_only_its_own_history(self):
        other_sid = uuid4()
        _ = await DatabaseService.create_session(
            session_id=other_sid,
            user_pk=self.user_pk,
            operation=OperationType.GENERATE,
            repo_uri="https://example.com/bar.git",
            terraform_prv=TerraformProvider.AZURE,
            scope_id="sub-456",
            branch_name="Kumoss/y",
            query="another one",
            iac_path="infra",
        )

        ctx = await DatabaseService.get_session_context(self.sid)
        ctx.history.append_turn(user_msg="hi", assistant_msg="hello")
        await DatabaseService.update_history(ctx)

        other = await DatabaseService.get_session_context(other_sid)
        self.assertEqual(other.history.serialize(), [])


class TestPullRequestFreshness(_SessionBase):
    async def test_add_overwrites_the_cached_empty_list(self):
        # Prime the cache with the (valid) empty state.
        with self.assertRaises(SessionTerminal):
            _ = await DatabaseService.get_pull_requests(self.sid)

        await DatabaseService.add_pull_request(
            self.sid, "https://github.com/org/repo/pull/42", 42
        )
        prs = await DatabaseService.get_pull_requests(self.sid)
        self.assertEqual(
            [pr.url for pr in prs], ["https://github.com/org/repo/pull/42"]
        )
        self.assertEqual([pr.number for pr in prs], [42])

    async def test_pr_attaches_to_the_latest_round(self):
        _ = await DatabaseService.create_round(self.sid, "add a vnet")
        await DatabaseService.add_pull_request(
            self.sid, "https://github.com/org/repo/pull/7", 7
        )

        detail = await DatabaseService.get_session_detail(self.sid)
        self.assertEqual(len(detail.rounds), 2)
        self.assertEqual(detail.rounds[0].pull_requests, [])
        self.assertEqual(
            [pr.url for pr in detail.rounds[1].pull_requests],
            ["https://github.com/org/repo/pull/7"],
        )
        # The session-scoped read still aggregates across rounds.
        prs = await DatabaseService.get_pull_requests(self.sid)
        self.assertEqual([pr.url for pr in prs], ["https://github.com/org/repo/pull/7"])

    async def test_session_without_rounds_rejects_prs(self):
        # Only possible for rows written outside create_session (which
        # always opens round 1); the guard must still be explicit.
        orphan_uuid = uuid4()
        _ = await db.create(
            Session,
            user_id=self.user_pk,
            uuid=orphan_uuid,
            operation=OperationType.GENERATE,
        )
        with self.assertRaises(SessionConflict):
            await DatabaseService.add_pull_request(
                orphan_uuid, "https://github.com/org/repo/pull/9", 9
            )

    async def test_provider_round_trips_as_native_enum(self):
        await DatabaseService.add_pull_request(
            self.sid, "https://github.com/org/repo/pull/1", 1
        )
        row = await db.get_by(PullRequest, url="https://github.com/org/repo/pull/1")
        self.assertIsNotNone(row)
        self.assertIs(row.provider, GitProviderName.GITHUB)
        prs = await DatabaseService.get_pull_requests(self.sid)
        self.assertEqual(prs[0].provider, "GITHUB")


class TestRounds(_SessionBase):
    async def test_create_session_opens_round_one(self):
        detail = await DatabaseService.get_session_detail(self.sid)
        self.assertEqual([r.number for r in detail.rounds], [1])
        row = await db.get_by(Round, number=1)
        self.assertEqual(row.query, "create a resource group")

    async def test_create_round_increments_number_and_stores_query(self):
        rid = await DatabaseService.create_round(self.sid, "add a vnet")
        row = await db.get_by(Round, id=rid)
        self.assertEqual(row.number, 2)
        self.assertEqual(row.query, "add a vnet")

    async def test_statuses_attach_to_the_latest_round(self):
        rid = await DatabaseService.create_round(self.sid, "add a vnet")
        await DatabaseService.mark_session_status(
            self.sid, SessionStatus.GENERATING, "working"
        )
        detail = await DatabaseService.get_session_detail(self.sid)
        self.assertEqual(
            [st.status for st in detail.rounds[0].statuses], [SessionStatus.STARTED]
        )
        self.assertEqual(
            [st.status for st in detail.rounds[1].statuses],
            [SessionStatus.GENERATING],
        )
        self.assertEqual(detail.rounds[1].id, rid)
        # The timeline is the rounds' statuses concatenated in round
        # order; the payload no longer ships a second, flat copy.
        self.assertFalse(hasattr(detail, "statuses"))
        self.assertEqual(
            [st.status for r in detail.rounds for st in r.statuses],
            [SessionStatus.STARTED, SessionStatus.GENERATING],
        )
        # The cheap latest-status field the list view polls stays.
        self.assertIs(detail.current_status, SessionStatus.GENERATING)


class TestInFlightEnforcement(_SessionBase):
    async def test_acquire_is_a_real_cas(self):
        await DatabaseService.acquire_in_flight(self.sid)
        with self.assertRaises(SessionConflict):
            await DatabaseService.acquire_in_flight(self.sid)
        await DatabaseService.release_in_flight(self.sid)
        # Reacquirable after release.
        await DatabaseService.acquire_in_flight(self.sid)
        await DatabaseService.release_in_flight(self.sid)

    async def test_completed_session_can_be_resumed(self):
        await DatabaseService.mark_completed(self.sid, "done")
        await DatabaseService.acquire_in_flight(self.sid)
        await DatabaseService.release_in_flight(self.sid)

    async def test_failed_session_cannot_be_resumed(self):
        await DatabaseService.mark_failed(self.sid, "boom")
        with self.assertRaises(SessionTerminal):
            await DatabaseService.acquire_in_flight(self.sid)

    async def test_uncompleted_session_can_be_resumed(self):
        await DatabaseService.mark_uncompleted(self.sid, "gave up")
        await DatabaseService.acquire_in_flight(self.sid)
        await DatabaseService.release_in_flight(self.sid)

    async def test_live_statuses_do_not_block_acquire(self):
        await DatabaseService.mark_session_status(
            self.sid, SessionStatus.GENERATING, "working"
        )
        await DatabaseService.acquire_in_flight(self.sid)
        await DatabaseService.release_in_flight(self.sid)

    async def test_unknown_session_is_not_found(self):
        with self.assertRaises(SessionTerminal):
            await DatabaseService.acquire_in_flight(uuid4())


class TestFinishedSessionDetailCache(_SessionBase):
    def _detail_key(self) -> str:
        return f"kumoss:v1:session:{self.sid}:detail"

    async def test_live_session_detail_is_never_cached(self):
        await DatabaseService.mark_session_status(
            self.sid, SessionStatus.GENERATING, "working"
        )
        _ = await DatabaseService.get_session_detail(self.sid)
        raw = await redis_client.connection.client.get(self._detail_key())
        self.assertIsNone(raw)

    async def test_finished_detail_is_cached_and_identical(self):
        await DatabaseService.mark_failed(self.sid, "boom")
        first = await DatabaseService.get_session_detail(self.sid)
        raw = await redis_client.connection.client.get(self._detail_key())
        self.assertIsNotNone(raw)
        # Second read is served from the cache and must round-trip exactly.
        second = await DatabaseService.get_session_detail(self.sid)
        self.assertEqual(first, second)

    async def test_report_type_and_query_survive_the_cache(self):
        # DB is wiped per test, so the only round is the one create_session
        # opened; add_report is DB-only and presigning is local, so no
        # object-storage round-trip is involved.
        [rnd] = await db.list_by(Round)
        _ = await DatabaseService.add_report(
            round_id=rnd.id,
            report_type=ReportType.APPLY,
            uri=f"sessions/{self.sid}/rounds/{rnd.id}/reports/apply-t.json",
            content_type="application/json",
            file_size_bytes=2,
        )
        await DatabaseService.mark_failed(self.sid, "boom")

        first = await DatabaseService.get_session_detail(self.sid)  # writes cache
        second = await DatabaseService.get_session_detail(self.sid)  # cached copy
        for detail in (first, second):
            [report] = detail.rounds[0].reports
            self.assertIs(report.type, ReportType.APPLY)
            self.assertEqual(detail.rounds[0].query, "create a resource group")

    async def test_stale_shaped_cache_entry_falls_back_to_the_database(self):
        # Old read-model shape: a round's artifacts were single `report`/
        # `plan` objects (now `reports`/`plans` lists) and the timeline
        # lived in a top-level `statuses` field (now removed). A key
        # written under that old shape must be treated as a cache miss,
        # not raise pydantic.ValidationError out of get_session_detail.
        [rnd] = await db.list_by(Round)
        _ = await DatabaseService.add_report(
            round_id=rnd.id,
            report_type=ReportType.APPLY,
            uri=f"sessions/{self.sid}/rounds/{rnd.id}/reports/apply-t.json",
            content_type="application/json",
            file_size_bytes=2,
        )
        await DatabaseService.mark_failed(self.sid, "boom")

        old_shaped = {
            "uuid": str(self.sid),
            "username": self.username,
            "operation": OperationType.GENERATE.value,
            "provider": TerraformProvider.AZURE.value,
            "first_query": None,
            "workspace_uri": "https://example.com/foo.git",
            "current_status": SessionStatus.FAILED.value,
            "in_flight": False,
            "is_blocked": False,
            "created_at": "2024-01-01T00:00:00",
            "updated_at": "2024-01-01T00:00:00",
            "workspace": {
                "uri": "https://example.com/foo.git",
                "branch": "Nebula/x",
                "root_path": None,
            },
            "scope_id": "sub-123",
            "statuses": [],
            "rounds": [
                {
                    "id": rnd.id,
                    "number": rnd.number,
                    "query": "create a resource group",
                    "statuses": [],
                    "report": None,
                    "plan": None,
                    "code_changes": [],
                    "pull_requests": [],
                    "created_at": "2024-01-01T00:00:00",
                }
            ],
            "history": None,
        }
        await redis_client.set_json(self._detail_key(), old_shaped)

        detail = await DatabaseService.get_session_detail(self.sid)

        [report] = detail.rounds[0].reports
        self.assertIs(report.type, ReportType.APPLY)
        self.assertEqual(detail.rounds[0].plans, [])
        self.assertEqual(detail.rounds[0].query, "create a resource group")
        self.assertIs(detail.current_status, SessionStatus.FAILED)

    async def test_admin_variant_is_not_served_from_cache(self):
        await DatabaseService.mark_failed(self.sid, "boom")
        _ = await DatabaseService.get_session_detail(self.sid)  # populate
        admin = await DatabaseService.get_session_detail(self.sid, include_history=True)
        # The cached copy has history=None; the admin surface must not.
        self.assertIsNotNone(admin.history)

    async def test_set_lock_drops_the_cached_detail(self):
        await DatabaseService.mark_failed(self.sid, "boom")
        _ = await DatabaseService.get_session_detail(self.sid)  # populate
        self.assertTrue(await DatabaseService.set_lock(self.sid, True))
        detail = await DatabaseService.get_session_detail(self.sid)
        self.assertTrue(detail.is_blocked)

    async def test_terminal_status_key_gets_a_long_ttl(self):
        await DatabaseService.mark_session_status(
            self.sid, SessionStatus.GENERATING, "working"
        )
        status_key = f"kumoss:v1:session:{self.sid}:status:last"
        live_ttl = await redis_client.connection.client.ttl(status_key)
        self.assertLessEqual(live_ttl, 6 * 60)

        await DatabaseService.mark_failed(self.sid, "boom")
        terminal_ttl = await redis_client.connection.client.ttl(status_key)
        self.assertGreater(terminal_ttl, 24 * 60 * 60)

    async def test_uncompleted_stays_live_for_the_cache(self):
        await DatabaseService.mark_uncompleted(self.sid, "gave up")
        status_key = f"kumoss:v1:session:{self.sid}:status:last"
        live_ttl = await redis_client.connection.client.ttl(status_key)
        self.assertLessEqual(live_ttl, 6 * 60)

        _ = await DatabaseService.get_session_detail(self.sid)
        raw = await redis_client.connection.client.get(self._detail_key())
        self.assertIsNone(raw)


class TestRoundArtifactLists(_SessionBase):
    """A drift round stores several plans per pass; all of them must surface."""

    async def test_every_plan_of_a_round_is_returned_oldest_first(self):
        [rnd] = await db.list_by(Round)
        # One drift pass writes the diff and the plan that resolved it; a
        # second reconciliation iteration adds one more.
        ids = [
            await DatabaseService.add_terraform_plan(
                round_id=rnd.id,
                targets=[],
                uri=f"sessions/{self.sid}/rounds/{rnd.id}/plans/{name}.txt",
                content_type="text/plain",
                file_size_bytes=1,
            )
            for name in ("drift-1", "plan-1", "plan-2")
        ]

        detail = await DatabaseService.get_session_detail(self.sid)

        self.assertEqual([p.id for p in detail.rounds[0].plans], ids)

    async def test_every_report_of_a_round_is_returned_oldest_first(self):
        [rnd] = await db.list_by(Round)
        ids = [
            await DatabaseService.add_report(
                round_id=rnd.id,
                report_type=report_type,
                uri=f"sessions/{self.sid}/rounds/{rnd.id}/reports/{i}.json",
                content_type="application/json",
                file_size_bytes=2,
            )
            for i, report_type in enumerate((ReportType.DRIFT, ReportType.GENERATE))
        ]

        detail = await DatabaseService.get_session_detail(self.sid)

        self.assertEqual([r.id for r in detail.rounds[0].reports], ids)
        self.assertEqual(
            [r.type for r in detail.rounds[0].reports],
            [ReportType.DRIFT, ReportType.GENERATE],
        )

    async def test_a_round_without_artifacts_returns_empty_lists(self):
        detail = await DatabaseService.get_session_detail(self.sid)

        self.assertEqual(detail.rounds[0].plans, [])
        self.assertEqual(detail.rounds[0].reports, [])

    async def test_rounds_are_ordered_by_number(self):
        second = await DatabaseService.create_round(self.sid, "add a vnet")
        third = await DatabaseService.create_round(self.sid, "add a subnet")

        detail = await DatabaseService.get_session_detail(self.sid)

        # Clients reconstruct the timeline by concatenating rounds, so
        # their order is contractual, not incidental.
        self.assertEqual([r.number for r in detail.rounds], [1, 2, 3])
        self.assertEqual([r.id for r in detail.rounds[1:]], [second, third])
