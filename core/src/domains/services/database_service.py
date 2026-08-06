# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import asyncio
import math
import random
from datetime import datetime, timezone
from typing import Any, cast
from uuid import UUID

from sqlalchemy import func, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import selectinload


from src.domains.dto import (
    ArtifactRef,
    CodeChangeRef,
    PaginatedSessionSummary,
    PullRequestRef,
    RoundDetail,
    SessionDetail,
    SessionSummary,
    StatusEntry,
    TerraformPlanRef,
    WorkspaceRef,
)
from src.domains.entities import SessionContext
from src.domains.value_objects import ProviderFacts, Status, WorkspaceFacts
from src.domains.exceptions import (
    LastStatusError,
    SessionConflict,
    SessionTerminal,
)
from src.infrastructure.database.database import db
from src.infrastructure.database.models import (
    Artifact,
    CodeChange,
    TerraformPlan,
    TerraformProvider as DbTerraformProvider,
    PullRequest,
    Report,
    Round,
    Status as DbStatus,
    User,
    Session,
    Workspace,
    History,
)
from src.infrastructure.redis import redis_client
from src.infrastructure.storage import default_object_storage
from src.shared.config.system_config import system_config
from src.shared.constants import (
    OperationType,
    ReportType,
    SessionStatus,
    TerraformProvider,
)

# --- Cache configuration -------------------------------------------------
#
# Reads are served from Redis so every worker/replica shares one view and
# the cache survives restarts. Two flavours:
#
#   * write-once facts (id maps, workspace, provider, first query) never
#     change after ``create_session``, so they carry a long TTL and are
#     populated write-through at creation. No invalidation is ever needed.
#   * mutable reads (session context, history, last status, pull requests)
#     are written through on every mutation and read-repaired with SET NX
#     on a miss. Entries are never deleted: delete-on-write races
#     cache-aside readers (reader loads the old row -> writer commits and
#     deletes -> reader caches the old value), while write-through + NX
#     cannot go stale that way. The TTL is only a backstop for a lost
#     write-through SET (Redis briefly down), so volatile keys keep it
#     short.
#
# A third flavour exists for FINISHED sessions: once a session's latest
# status is terminal (COMPLETED / FAILED) it can never change again —
# ``acquire_in_flight`` enforces this — so the full detail aggregate is
# cached and the last-status key gets a long TTL. The only mutation still
# possible on a finished session is the admin ``set_lock`` toggle, which
# drops the cached detail.
#
# Keys are namespaced and versioned so a schema change can drop everything
# by bumping the prefix.

_CACHE_NS = "nebula:v1"

_TTL_FACTS = 4 * 24 * 60 * 60  # write-once facts; immutable, safe to keep long
_TTL_CONTEXT = 2 * 24 * 60 * 60  # session context; written through on save
_TTL_HISTORY = 2 * 24 * 60 * 60  # history payload; written through with context
_TTL_STATUS = 5 * 60  # last status; volatile + user-facing, heal lost SETs fast
_TTL_PR = 7 * 24 * 60 * 60  # pull requests; written through on add
# Finished-session aggregate; bounds the set_lock race. The aggregate
# embeds presigned artifact URLs, so storage.presign_expiry_seconds must
# outlive this TTL (+ jitter) — its config validator enforces a 30h floor.
_TTL_DETAIL = 24 * 60 * 60

# Session-level end states. Once a session's latest status is terminal it
# never changes again (enforced by acquire_in_flight), so anything derived
# from it is safe to cache aggressively.
_TERMINAL = frozenset({SessionStatus.COMPLETED, SessionStatus.FAILED})


def _ttl(base: int) -> int:
    """Base TTL plus up to ~10% jitter."""
    return base + random.randint(0, max(1, base // 10))


def _status_ttl(status: SessionStatus) -> int:
    """Terminal statuses never change: keep them as long as the facts."""
    return _ttl(_TTL_FACTS) if status in _TERMINAL else _ttl(_TTL_STATUS)


def _k_sid(session_id: UUID) -> str:
    return f"{_CACHE_NS}:map:sid:{session_id}"


def _k_user_id(username: str) -> str:
    return f"{_CACHE_NS}:map:user-id:{username}"


def _k_user_name(pk: int) -> str:
    return f"{_CACHE_NS}:map:user-name:{pk}"


def _k_workspace(session_id: UUID) -> str:
    return f"{_CACHE_NS}:session:{session_id}:workspace"


def _k_provider(session_id: UUID) -> str:
    return f"{_CACHE_NS}:session:{session_id}:provider"


def _k_first_query(session_id: UUID) -> str:
    return f"{_CACHE_NS}:session:{session_id}:first-query"


def _k_context(session_id: UUID) -> str:
    return f"{_CACHE_NS}:session:{session_id}:ctx"


def _k_last_status(session_id: UUID) -> str:
    return f"{_CACHE_NS}:session:{session_id}:status:last"


def _k_history(session_id: UUID) -> str:
    return f"{_CACHE_NS}:session:{session_id}:history"


def _k_pull_requests(session_id: UUID) -> str:
    return f"{_CACHE_NS}:session:{session_id}:prs"


def _k_detail(session_id: UUID) -> str:
    return f"{_CACHE_NS}:session:{session_id}:detail"


def _serialize_ctx(ctx: SessionContext) -> dict[str, Any]:
    """Reduce a SessionContext to the JSON-safe fields that rebuild it.

    Only the constructor inputs are stored; transient state (``call_dir``,
    artifacts) is intentionally left out of the cache.
    """

    return {
        "id": str(ctx.id),
        "user_id": ctx.user_id,
        "round_id": ctx.round_id,
        "repo_uri": ctx.repo_uri,
        "scope_id": ctx.scope_id,
        "operation_type": ctx.operation.value,
        "terraform_prv": ctx.terraform_prv.value,
        "branch_name": ctx.branch_name,
        "iac_path": ctx.iac_path,
        "history": ctx.history.serialize(),
    }


def _deserialize_ctx(data: dict[str, Any]) -> SessionContext:
    return SessionContext(
        id=UUID(data["id"]),
        user_id=data["user_id"],
        round_id=data["round_id"],
        repo_uri=data["repo_uri"],
        scope_id=data["scope_id"],
        operation_type=OperationType(data["operation_type"]),
        terraform_prv=TerraformProvider(data["terraform_prv"]),
        branch_name=data["branch_name"],
        iac_path=data["iac_path"],
        history=data["history"],
    )


class DatabaseService:
    """Stateless static DB helpers with a Redis read-through cache."""

    @staticmethod
    async def __map_session_id(uuid: UUID) -> int | None:
        """session uuid -> integer pk. Write-once."""

        async def _load() -> int | None:
            session: Session | None = await db.get_by(Session, uuid=uuid)
            return session.id if session is not None else None

        return await redis_client.get_or_set(_k_sid(uuid), _ttl(_TTL_FACTS), _load)

    @staticmethod
    async def __load_session(uuid: UUID) -> Session | None:
        # Not cached: the Session row carries mutable lock state (in_flight,
        # is_blocked) that must always be read fresh.
        session: Session | None = await db.get_by(Session, uuid=uuid)
        return session

    @staticmethod
    async def __map_user_id(username: str) -> int | None:
        """username -> user pk. Write-once."""

        async def _load() -> int | None:
            user: User | None = await db.get_by(User, username=username)
            return user.id if user is not None else None

        return await redis_client.get_or_set(
            _k_user_id(username), _ttl(_TTL_FACTS), _load
        )

    @staticmethod
    async def __map_user_name(pk: int) -> str | None:
        """user pk -> username. Write-once."""

        async def _load() -> str | None:
            user: User | None = await db.get_by(User, id=pk)
            return user.username if user is not None else None

        return await redis_client.get_or_set(_k_user_name(pk), _ttl(_TTL_FACTS), _load)

    @staticmethod
    async def __workspace_facts(session_id: UUID) -> WorkspaceFacts | None:
        """Write-once workspace fields for a session."""

        async def _load() -> dict[str, str] | None:
            sid = await DatabaseService.__map_session_id(session_id)
            ws: Workspace | None = await db.get_by(Workspace, session_id=sid)
            if ws is None:
                return None
            return {"uri": ws.uri, "branch": ws.branch, "root_path": ws.root_path}

        data = await redis_client.get_or_set(
            _k_workspace(session_id), _ttl(_TTL_FACTS), _load
        )
        return WorkspaceFacts(**data) if data is not None else None

    @staticmethod
    async def __provider_facts(session_id: UUID) -> ProviderFacts | None:
        """Write-once terraform-provider fields for a session."""

        async def _load() -> dict[str, str] | None:
            sid = await DatabaseService.__map_session_id(session_id)
            tp: DbTerraformProvider | None = await db.get_by(
                DbTerraformProvider, session_id=sid
            )
            if tp is None:
                return None
            return {"provider": tp.provider.value, "scope_id": tp.scope_id}

        data = await redis_client.get_or_set(
            _k_provider(session_id), _ttl(_TTL_FACTS), _load
        )
        if data is None:
            return None
        return ProviderFacts(
            provider=TerraformProvider(data["provider"]), scope_id=data["scope_id"]
        )

    @staticmethod
    async def __first_query(session_id: UUID) -> str | None:
        """Write-once first query for a session."""

        async def _load() -> str | None:
            sid = await DatabaseService.__map_session_id(session_id)
            his: History | None = await db.get_by(History, session_id=sid)
            return his.first_query if his else None

        return await redis_client.get_or_set(
            _k_first_query(session_id), _ttl(_TTL_FACTS), _load
        )

    @staticmethod
    async def __history_payload(session_id: UUID) -> list[dict[str, str]] | None:
        """Cache-aside read of the conversation payload (turns) for a session."""

        async def _load() -> list[dict[str, str]] | None:
            sid = await DatabaseService.__map_session_id(session_id)
            his: History | None = await db.get_by(History, session_id=sid)
            return his.payload if his is not None else None

        return await redis_client.get_or_set(
            _k_history(session_id), _ttl(_TTL_HISTORY), _load
        )

    @staticmethod
    async def __load_pull_requests(sid: int | None) -> list[dict[str, str]]:
        async with db.session() as sess:
            stmt = (
                select(PullRequest)
                .join(Round, PullRequest.round_id == Round.id)
                .where(Round.session_id == sid)
                .order_by(Round.number, PullRequest.id)
            )
            prs = list((await sess.execute(stmt)).scalars().all())
        # Empty list is a valid cacheable state (most sessions have none).
        return [{"provider": pr.provider.name, "url": pr.url} for pr in prs]

    @staticmethod
    async def __latest_round_id(sid: int) -> int | None:
        """Pk of the session's highest-numbered round, or None if none exist."""
        async with db.session() as sess:
            stmt = (
                select(Round.id)
                .where(Round.session_id == sid)
                .order_by(Round.number.desc())
                .limit(1)
            )
            return (await sess.execute(stmt)).scalar_one_or_none()

    @staticmethod
    async def __pull_requests(session_id: UUID) -> list[dict[str, str]]:
        """Cached read of all pull requests for a session."""

        async def _load() -> list[dict[str, str]]:
            sid = await DatabaseService.__map_session_id(session_id)
            return await DatabaseService.__load_pull_requests(sid)

        data = await redis_client.get_or_set(
            _k_pull_requests(session_id), _ttl(_TTL_PR), _load
        )
        return data if data is not None else []

    @staticmethod
    async def __create_status(
        session_id: UUID, status: SessionStatus, msg: str, round_id: int | None = None
    ) -> DbStatus:
        sid = await DatabaseService.__map_session_id(session_id)
        if sid is None:
            raise SessionTerminal(
                message=f"Session {session_id} not found.",
                error_code=404,
            )
        if not round_id:
            round_id = await DatabaseService.__latest_round_id(sid)
        if not round_id:
            raise SessionConflict(
                message=f"Session {session_id} has no rounds; cannot record a status.",
                error_code=409,
            )
        return await db.create(
            DbStatus,
            session_id=sid,
            round_id=round_id,
            status=status,
            message=msg,
        )

    @staticmethod
    async def create_session(
        session_id: UUID,
        user_id: str,
        operation: OperationType,
        repo_uri: str,
        terraform_prv: TerraformProvider,
        scope_id: str,
        branch_name: str,
        query: str,
        iac_path: str | None = None,
    ) -> Session:
        user_pk: int | None = await DatabaseService.__map_user_id(user_id)
        if user_pk is None:
            user: User = await db.create(User, username=user_id)
            user_pk = user.id
            # Write-through the new user mappings (immutable once created).
            await redis_client.set_json_many(
                [
                    (_k_user_id(user_id), user_pk, _ttl(_TTL_FACTS)),
                    (_k_user_name(user_pk), user_id, _ttl(_TTL_FACTS)),
                ]
            )

        session: Session = await db.create(
            Session,
            user_id=user_pk,
            uuid=session_id,
            operation=operation,
        )
        _ = await db.create(
            Workspace,
            session_id=session.id,
            uri=repo_uri,
            branch=branch_name,
            root_path=iac_path,
        )
        _ = await db.create(
            DbTerraformProvider,
            session_id=session.id,
            provider=terraform_prv,
            scope_id=scope_id,
        )
        _ = await db.create(
            History,
            session_id=session.id,
            first_query=query,
        )
        round = await db.create(
            Round,
            session_id=session.id,
            number=1,
            query=query,
        )
        st = await db.create(
            DbStatus,
            session_id=session.id,
            round_id=round.id,
            status=SessionStatus.STARTED,
            message=f"Session '{str(session_id)}' started.",
        )

        await redis_client.set_json_many(
            [
                (_k_sid(session_id), session.id, _ttl(_TTL_FACTS)),
                (
                    _k_workspace(session_id),
                    {"uri": repo_uri, "branch": branch_name, "root_path": iac_path},
                    _ttl(_TTL_FACTS),
                ),
                (
                    _k_provider(session_id),
                    {"provider": terraform_prv.value, "scope_id": scope_id},
                    _ttl(_TTL_FACTS),
                ),
                (_k_first_query(session_id), query, _ttl(_TTL_FACTS)),
                (
                    _k_last_status(session_id),
                    {"status": st.status, "message": st.message},
                    _ttl(_TTL_STATUS),
                ),
            ]
        )
        return session

    @staticmethod
    async def get_session_context(session_id: UUID) -> SessionContext:
        async def _load() -> dict[str, Any]:
            session: Session | None = await DatabaseService.__load_session(session_id)
            if session is None:
                raise SessionTerminal(
                    message=f"Session {session_id} not found.",
                    error_code=404,
                )
            username, workspace, provider, payload, round_id = await asyncio.gather(
                DatabaseService.__map_user_name(session.user_id),
                DatabaseService.__workspace_facts(session_id),
                DatabaseService.__provider_facts(session_id),
                DatabaseService.__history_payload(session_id),
                DatabaseService.__latest_round_id(session.id),
            )
            if username is None:
                raise SessionTerminal(
                    message=f"Session {session_id} has no owning user",
                    error_code=500,
                )
            if workspace is None:
                raise SessionTerminal(
                    message=f"Session {session_id} does not have a workspace",
                    error_code=404,
                )
            if provider is None:
                raise SessionTerminal(
                    message=f"Session {session_id} does not have an associated cloud provider",
                    error_code=404,
                )
            if round_id is None:
                raise SessionConflict(
                    message=f"Session {session_id} does not have an associated round.",
                    error_code=409,
                )
            ctx = SessionContext(
                id=session.uuid,
                user_id=username,
                round_id=round_id,
                repo_uri=workspace.uri,
                scope_id=provider.scope_id,
                operation_type=session.operation,
                terraform_prv=provider.provider,
                branch_name=workspace.branch,
                iac_path=workspace.root_path,
                history=payload,
            )
            return _serialize_ctx(ctx)

        data = await redis_client.get_or_set(
            _k_context(session_id), _ttl(_TTL_CONTEXT), _load
        )
        return _deserialize_ctx(data)

    @staticmethod
    async def __current_status(session_id: UUID) -> SessionStatus:
        """Latest recorded status, STARTED when none has been written yet."""
        try:
            status: Status = await DatabaseService.get_last_status(session_id)
        except LastStatusError:
            return SessionStatus.STARTED
        return status.status

    @staticmethod
    async def __construct_summary(s: Session) -> SessionSummary:
        (
            workspace,
            provider,
            username,
            first_query,
            current_status,
        ) = await asyncio.gather(
            DatabaseService.__workspace_facts(s.uuid),
            DatabaseService.__provider_facts(s.uuid),
            DatabaseService.__map_user_name(s.user_id),
            DatabaseService.__first_query(s.uuid),
            DatabaseService.__current_status(s.uuid),
        )
        if workspace is None or provider is None:
            raise SessionTerminal(
                message=f"Session {s.uuid} is misconfigured",
                error_code=500,
            )
        return SessionSummary(
            uuid=s.uuid,
            username=username,
            operation=s.operation,
            provider=provider.provider,
            first_query=first_query,
            workspace_uri=workspace.uri,
            current_status=current_status,
            in_flight=s.in_flight,
            is_blocked=s.is_blocked,
            created_at=s.created_at,
            updated_at=s.updated_at,
        )

    @staticmethod
    async def get_session_summary(session_id: UUID) -> SessionSummary:
        s: Session | None = await DatabaseService.__load_session(session_id)
        if not s:
            raise SessionTerminal(
                message=f"Session {session_id} not found.",
                error_code=404,
            )
        return await DatabaseService.__construct_summary(s)

    @staticmethod
    async def list_sessions(
        user_id: str,
        operation: OperationType | None = None,
        status: SessionStatus | None = None,
        search: str | None = None,
        order_by: str = "created_at",
        order_desc: bool = True,
        offset: int = 0,
        limit: int = 20,
    ) -> PaginatedSessionSummary:
        user_pk: int | None = await DatabaseService.__map_user_id(user_id)
        if user_pk is None:
            raise SessionTerminal(
                message=f"User {user_id} not found",
                error_code=404,
            )

        async with db.session() as sess:
            stmt = select(Session).where(Session.user_id == user_pk)
            if operation is not None:
                stmt = stmt.where(Session.operation == operation)
            if search:
                pattern = f"%{search}%"
                stmt = (
                    stmt.join(History, History.session_id == Session.id)
                    .join(Workspace, Workspace.session_id == Session.id)
                    .where(
                        History.first_query.ilike(pattern)
                        | Workspace.uri.ilike(pattern)
                    )
                )
            if status is not None:
                # Filter on each session's most recent status row; max(id)
                # is the append-order proxy for "latest".
                latest = (
                    select(
                        DbStatus.session_id,
                        func.max(DbStatus.id).label("last_id"),
                    )
                    .group_by(DbStatus.session_id)
                    .subquery()
                )
                stmt = (
                    stmt.join(latest, latest.c.session_id == Session.id)
                    .join(DbStatus, DbStatus.id == latest.c.last_id)
                    .where(DbStatus.status == status)
                )

            count_stmt = select(func.count()).select_from(stmt.subquery())
            count: int = (await sess.execute(count_stmt)).scalar_one()

            order_col = getattr(Session, order_by, Session.created_at)
            stmt = (
                stmt.order_by(order_col.desc() if order_desc else order_col.asc())
                .offset(offset)
                .limit(limit)
            )
            sessions = list((await sess.execute(stmt)).scalars().all())

        # Summaries only touch the cache / point reads, so build the whole
        # page concurrently instead of paying the fan-out sequentially.
        summaries: list[SessionSummary] = list(
            await asyncio.gather(
                *(DatabaseService.__construct_summary(s) for s in sessions)
            )
        )

        return PaginatedSessionSummary(
            items=summaries,
            total=count,
            page=offset // limit + 1,
            page_size=limit,
            total_pages=math.ceil(count / limit) if count > 0 else 0,
        )

    # --- Session detail aggregate -----------------------------------------

    @staticmethod
    def __artifact_url(artifact: Artifact) -> str:
        """Client-fetchable URL for an artifact."""
        return default_object_storage().presigned_get_url(artifact.uri)

    @staticmethod
    def __artifact_fields(row: Report | TerraformPlan | CodeChange) -> dict[str, Any]:
        return {
            "id": row.id,
            "url": DatabaseService.__artifact_url(row.artifact),
            "content_type": row.artifact.content_type,
            "file_size_bytes": row.artifact.file_size_bytes,
            "created_at": row.created_at,
        }

    @staticmethod
    def __status_entry(st: DbStatus) -> StatusEntry:
        return StatusEntry(
            status=st.status,
            message=st.message or None,
            created_at=st.created_at,
        )

    @staticmethod
    def __round_detail(r: Round) -> RoundDetail:
        # A round holds at most one meaningful report/plan; latest wins.
        report = max(r.reports, key=lambda x: (x.created_at, x.id), default=None)
        plan = max(r.terraform_plans, key=lambda x: (x.created_at, x.id), default=None)
        return RoundDetail(
            id=r.id,
            number=r.number,
            statuses=[
                DatabaseService.__status_entry(st)
                for st in sorted(r.statuses, key=lambda st: (st.created_at, st.id))
            ],
            report=ArtifactRef(**DatabaseService.__artifact_fields(report))
            if report
            else None,
            plan=TerraformPlanRef(
                **DatabaseService.__artifact_fields(plan), targets=plan.targets
            )
            if plan
            else None,
            code_changes=[
                CodeChangeRef(
                    **DatabaseService.__artifact_fields(c), file_name=c.file_name
                )
                for c in sorted(r.code_changes, key=lambda c: (c.created_at, c.id))
            ],
            pull_requests=[
                PullRequestRef(provider=pr.provider.name, url=pr.url)
                for pr in sorted(r.pull_requests, key=lambda pr: (pr.created_at, pr.id))
            ],
            created_at=r.created_at,
        )

    @staticmethod
    async def get_session_detail(
        session_id: UUID, include_history: bool = False
    ) -> SessionDetail:
        """Full session aggregate: facts, timeline, and per-round artifacts.

        Live sessions are always read fresh: the aggregate mutates while a
        session runs and the push channel triggers client refetches of this
        exact read model. Finished sessions can never change again
        (``acquire_in_flight`` refuses them), so those are served from a
        cached copy. The admin variant (``include_history=True``) is always
        read fresh.
        """
        if not include_history:
            cached = await redis_client.get_json(_k_detail(session_id))
            if cached is not None:
                return SessionDetail.model_validate(cached)

        async with db.session() as sess:
            stmt = (
                select(Session)
                .where(Session.uuid == session_id)
                .options(
                    selectinload(Session.workspaces),
                    selectinload(Session.terraform_providers),
                    selectinload(Session.histories),
                    selectinload(Session.statuses),
                    selectinload(Session.rounds).selectinload(Round.statuses),
                    selectinload(Session.rounds).selectinload(Round.pull_requests),
                    selectinload(Session.rounds)
                    .selectinload(Round.reports)
                    .selectinload(Report.artifact),
                    selectinload(Session.rounds)
                    .selectinload(Round.terraform_plans)
                    .selectinload(TerraformPlan.artifact),
                    selectinload(Session.rounds)
                    .selectinload(Round.code_changes)
                    .selectinload(CodeChange.artifact),
                )
            )
            result = await sess.execute(stmt)
            s: Session | None = result.scalar_one_or_none()

        if s is None:
            raise SessionTerminal(
                message=f"Session {session_id} not found.",
                error_code=404,
            )
        if not s.workspaces or not s.terraform_providers:
            raise SessionTerminal(
                message=f"Session {session_id} is missconfigured",
                error_code=500,
            )

        workspace = s.workspaces[0]
        provider = s.terraform_providers[0]
        history = s.histories[0] if s.histories else None
        # max(id) is the append-order proxy for "latest" — the same
        # convention get_last_status and the list_sessions filter use.
        current = max(s.statuses, key=lambda st: st.id, default=None)
        # Every status belongs to a round (NOT NULL); the session-level
        # view is the full timeline across all rounds.
        session_statuses = sorted(
            s.statuses,
            key=lambda st: (st.created_at, st.id),
        )

        detail = SessionDetail(
            uuid=s.uuid,
            username=await DatabaseService.__map_user_name(s.user_id),
            operation=s.operation,
            provider=provider.provider,
            first_query=history.first_query if history else None,
            workspace_uri=workspace.uri,
            current_status=current.status if current else SessionStatus.STARTED,
            in_flight=s.in_flight,
            is_blocked=s.is_blocked,
            created_at=s.created_at,
            updated_at=s.updated_at,
            workspace=WorkspaceRef(
                uri=workspace.uri,
                branch=workspace.branch,
                root_path=workspace.root_path,
            ),
            scope_id=provider.scope_id,
            statuses=[DatabaseService.__status_entry(st) for st in session_statuses],
            rounds=[DatabaseService.__round_detail(r) for r in s.rounds],
            history=history.payload if include_history and history else None,
        )

        # A finished session's aggregate is immutable (only the admin
        # set_lock toggle can still touch it, and that drops this key).
        if (
            not include_history
            and detail.current_status in _TERMINAL
            and not detail.in_flight
        ):
            await redis_client.set_json(
                _k_detail(session_id),
                detail.model_dump(mode="json"),
                ttl=_ttl(_TTL_DETAIL),
            )
        return detail

    @staticmethod
    async def update_history(ctx: SessionContext) -> None:
        sid = await DatabaseService.__map_session_id(ctx.id)
        if sid is None:
            raise SessionConflict(
                message=f"Failed to update history on session {ctx.id}.",
                error_code=500,
            )
        async with db.transaction() as sess:
            stmt = (
                update(History)
                .where(History.session_id == sid)
                .values(
                    payload=ctx.history.serialize(),
                    updated_at=datetime.now(timezone.utc),
                )
            )
            res = await sess.execute(stmt)
            if cast(CursorResult[Any], res).rowcount != 1:
                raise SessionConflict(
                    message=f"Failed to update history on session {ctx.id}.",
                    error_code=500,
                )
        # Write-through the fresh context + history (see cache notes above).
        await redis_client.set_json_many(
            [
                (_k_context(ctx.id), _serialize_ctx(ctx), _ttl(_TTL_CONTEXT)),
                (_k_history(ctx.id), ctx.history.serialize(), _ttl(_TTL_HISTORY)),
            ]
        )
        _ = await redis_client.invalidate(_k_detail(ctx.id))

    @staticmethod
    async def acquire_in_flight(session_id: UUID) -> None:
        """Compare-and-set the in-flight lock, refusing finished sessions.

        One atomic UPDATE is both the CAS (``in_flight`` must be false) and
        the terminal guard (latest status must not be COMPLETED/FAILED), so
        two runners can never both win the lock and a finished session can
        never be resumed — which is what makes finished sessions safe to
        cache aggressively.
        """
        last_status = (
            select(DbStatus.status)
            .where(DbStatus.session_id == Session.id)
            .order_by(DbStatus.id.desc())
            .limit(1)
            .scalar_subquery()
        )
        async with db.transaction() as sess:
            stmt = (
                update(Session)
                .where(
                    Session.uuid == session_id,
                    Session.in_flight.is_(False),
                    # No status rows yet counts as live (implicit STARTED).
                    or_(last_status.is_(None), last_status.notin_(_TERMINAL)),
                )
                .values(in_flight=True, updated_at=datetime.now(timezone.utc))
            )
            res = await sess.execute(stmt)
            if cast(CursorResult[Any], res).rowcount == 1:
                return
        # Lost the CAS: reload once to report precisely why.
        session = await DatabaseService.__load_session(session_id)
        if session is None:
            raise SessionTerminal(
                message=f"Session {session_id} not found.",
                error_code=404,
            )
        if await DatabaseService.__current_status(session_id) in _TERMINAL:
            raise SessionTerminal(
                message=f"Session {session_id} is finished and cannot be resumed.",
                error_code=409,
            )
        raise SessionConflict(
            message=f"Session {session_id} already has an operation in flight.",
            error_code=409,
        )

    @staticmethod
    async def release_in_flight(session_id: UUID) -> None:
        """Atomic compare-and-set: True if we free lock, False otherwise."""
        async with db.transaction() as sess:
            stmt = (
                update(Session)
                .where(Session.uuid == session_id)
                .values(in_flight=False, updated_at=datetime.now(timezone.utc))
            )
            res = await sess.execute(stmt)
            if cast(CursorResult[Any], res).rowcount != 1:
                raise SessionConflict(
                    message=f"Failed to release in-flight lock on session {session_id}.",
                    error_code=500,
                )

    @staticmethod
    async def mark_session_status(
        session_id: UUID,
        status: SessionStatus,
        msg: str,
        round_id: int | None = None,
    ) -> None:
        """Append a status row; attaches to the session's latest round
        unless ``round_id`` targets a specific one."""
        _ = await DatabaseService.__create_status(session_id, status, msg, round_id)
        # Write-through the new latest status (see cache notes above).
        await redis_client.set_json(
            _k_last_status(session_id),
            {"status": status.value, "message": msg},
            ttl=_status_ttl(status),
        )
        # Any status transition invalidates a cached detail aggregate
        # (a no-op for live sessions, which are never cached).
        _ = await redis_client.invalidate(_k_detail(session_id))

    @staticmethod
    async def get_last_status(session_id: UUID) -> Status:
        async def _load() -> dict[str, str] | None:
            sid = await DatabaseService.__map_session_id(session_id)
            # max(id) is the append-order proxy for "latest", immune to
            # created_at ties (same convention as the list_sessions filter).
            status_model = await db.list_by(
                model=DbStatus,
                order_by="id",
                order_desc=True,
                limit=1,
                session_id=sid,
            )
            if len(status_model) != 1:
                return None
            return {
                "status": status_model[0].status.value,
                "message": status_model[0].message,
            }

        data = await redis_client.get_or_set(
            _k_last_status(session_id),
            # Read-repair keeps terminal statuses as long as the write path.
            lambda loaded: _status_ttl(SessionStatus(loaded["status"])),
            _load,
        )
        if data is None:
            raise LastStatusError(f"No status records for session {session_id}", 500)
        return Status(SessionStatus(data["status"]), data["message"])

    @staticmethod
    async def mark_failed(session_id: UUID, msg: str) -> None:
        await DatabaseService.mark_session_status(session_id, SessionStatus.FAILED, msg)

    @staticmethod
    async def mark_completed(session_id: UUID, msg: str) -> None:
        await DatabaseService.mark_session_status(
            session_id, SessionStatus.COMPLETED, msg
        )

    @staticmethod
    async def mark_uncompleted(session_id: UUID, msg: str) -> None:
        await DatabaseService.mark_session_status(
            session_id, SessionStatus.UNCOMPLETED, msg
        )

    @staticmethod
    async def set_lock(session_id: UUID, lock: bool) -> bool:
        async with db.transaction() as sess:
            stmt = (
                update(Session)
                .where(Session.uuid == session_id)
                .values(is_blocked=lock, updated_at=datetime.now(timezone.utc))
            )
            res = await sess.execute(stmt)
            updated = cast(CursorResult[Any], res).rowcount == 1
        if updated:
            # is_blocked is part of the cached detail aggregate and this is
            # the one mutation still allowed on a finished session: drop the
            # cached copy so the next read rebuilds with the new flag.
            _ = await redis_client.invalidate(_k_detail(session_id))
        return updated

    # --- Round / artifact write path ---------------------------------------
    #
    # No cache invalidation here: rounds and artifacts are only written
    # while a session holds the in-flight lock, i.e. while it is live —
    # and live sessions are never cached in the detail key.

    @staticmethod
    async def create_round(session_id: UUID, query: str) -> int:
        """Open the next generation round for a session, returning its pk.

        ``query`` is the user prompt that opened the round. Numbering
        relies on the session's in-flight lock (one runner per session);
        the unique constraint on (session_id, number) backstops any race.
        """
        sid = await DatabaseService.__map_session_id(session_id)
        if sid is None:
            raise SessionTerminal(
                message=f"Session {session_id} not found.",
                error_code=404,
            )
        last: list[Round] = await db.list_by(
            Round, order_by="number", order_desc=True, limit=1, session_id=sid
        )
        number = last[0].number + 1 if last else 1
        round_: Round = await db.create(
            Round, session_id=sid, number=number, query=query
        )
        return round_.id

    @staticmethod
    async def __create_artifact(
        uri: str, content_type: str, file_size_bytes: int
    ) -> int:
        artifact: Artifact = await db.create(
            Artifact,
            uri=uri,
            content_type=content_type,
            file_size_bytes=file_size_bytes,
        )
        return artifact.id

    @staticmethod
    async def add_report(
        round_id: int,
        report_type: ReportType,
        uri: str,
        content_type: str,
        file_size_bytes: int,
    ) -> int:
        aid = await DatabaseService.__create_artifact(
            uri, content_type, file_size_bytes
        )
        report: Report = await db.create(
            Report, round_id=round_id, artifact_id=aid, type=report_type
        )
        return report.id

    @staticmethod
    async def add_terraform_plan(
        round_id: int,
        targets: list[str],
        uri: str,
        content_type: str,
        file_size_bytes: int,
    ) -> int:
        aid = await DatabaseService.__create_artifact(
            uri, content_type, file_size_bytes
        )
        plan: TerraformPlan = await db.create(
            TerraformPlan, round_id=round_id, artifact_id=aid, targets=targets
        )
        return plan.id

    @staticmethod
    async def add_code_change(
        round_id: int,
        file_name: str,
        uri: str,
        content_type: str,
        file_size_bytes: int,
    ) -> int:
        aid = await DatabaseService.__create_artifact(
            uri, content_type, file_size_bytes
        )
        change: CodeChange = await db.create(
            CodeChange, round_id=round_id, artifact_id=aid, file_name=file_name
        )
        return change.id

    @staticmethod
    async def get_pull_requests(session_id: UUID) -> list[dict[str, str]]:
        prs = await DatabaseService.__pull_requests(session_id)
        if not prs:
            raise SessionTerminal(
                message=f"Session {session_id} does not have any associated Pull Requests",
                error_code=404,
            )
        return prs

    @staticmethod
    async def add_pull_request(session_id: UUID, url: str) -> None:
        """Persist a new Pull Request on the session's latest round and
        write-through the refreshed list."""
        sid = await DatabaseService.__map_session_id(session_id)
        if sid is None:
            raise SessionTerminal(
                message=f"Session {session_id} not found.",
                error_code=404,
            )
        round_id = await DatabaseService.__latest_round_id(sid)
        if round_id is None:
            raise SessionConflict(
                message=f"Session {session_id} has no rounds; cannot attach a pull request.",
                error_code=409,
            )
        _ = await db.create(
            PullRequest,
            round_id=round_id,
            provider=system_config.git.provider,
            url=url,
        )
        # Re-read and write-through instead of deleting (see cache notes above).
        prs = await DatabaseService.__load_pull_requests(sid)
        await redis_client.set_json(
            _k_pull_requests(session_id), prs, ttl=_ttl(_TTL_PR)
        )
        _ = await redis_client.invalidate(_k_detail(session_id))
