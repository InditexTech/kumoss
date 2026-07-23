# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import random
from datetime import datetime, timezone
from typing import Any, cast
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.engine import CursorResult


from src.domains.dto import PaginatedSessionOverview, SessionOverview
from src.domains.entities import SessionContext
from src.domains.value_objects import Lock, ProviderFacts, Status, WorkspaceFacts
from src.domains.exceptions import (
    LastStatusError,
    SessionConflict,
    SessionTerminal,
)
from src.infrastructure.database.database import db
from src.infrastructure.database.models import (
    TerraformProvider as DbTerraformProvider,
    PullRequest,
    Status as DbStatus,
    User,
    Session,
    Workspace,
    History,
)
from src.infrastructure.redis import redis_client
from src.shared.constants import SessionStatus, TerraformProvider

# --- Cache configuration -------------------------------------------------
#
# Reads are served from Redis so every worker/replica shares one view and
# the cache survives restarts. Two flavours:
#
#   * write-once facts (id maps, workspace, provider, first query) never
#     change after ``create_session``, so they carry a long TTL and are
#     populated write-through at creation. No invalidation is ever needed.
#   * mutable reads (session context, last status, lock state) are
#     cache-aside on read and invalidated (delete-on-write) whenever the
#     source row changes, with a short TTL as a backstop.
#
# Keys are namespaced and versioned so a schema change can drop everything
# by bumping the prefix.

_CACHE_NS = "nebula:v1"

_TTL_FACTS = 4 * 24 * 60 * 60  # write-once facts; immutable, safe to keep long
_TTL_CONTEXT = 2 * 24 * 60 * 60  # session context; kept honest via delete-on-write
_TTL_STATUS = 2 * 60 * 60  # last status; polled often, delete-on-write on change
_TTL_LOCK = 5 * 60  # lock state; short backstop, delete-on-write on change


def _ttl(base: int) -> int:
    """Base TTL plus up to ~10% jitter."""
    return base + random.randint(0, max(1, base // 10))


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


def _k_lock(session_id: UUID) -> str:
    return f"{_CACHE_NS}:session:{session_id}:lock"


def _serialize_ctx(ctx: SessionContext) -> dict[str, Any]:
    """Reduce a SessionContext to the JSON-safe fields that rebuild it.

    Only the constructor inputs are stored; transient state (``call_dir``,
    artifacts) is intentionally left out of the cache.
    """
    return {
        "id": str(ctx.id),
        "user_id": ctx.user_id,
        "repo_uri": ctx.repo_uri,
        "scope_id": ctx.scope_id,
        "terraform_prv": ctx.terraform_prv.value,
        "branch_name": ctx.branch_name,
        "iac_path": ctx.iac_path,
        "history": ctx.history.serialize(),
    }


def _deserialize_ctx(data: dict[str, Any]) -> SessionContext:
    return SessionContext(
        id=UUID(data["id"]),
        user_id=data["user_id"],
        repo_uri=data["repo_uri"],
        scope_id=data["scope_id"],
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
    async def __load_history(session_id: UUID) -> History | None:
        # Not cached on its own: the payload is folded into the cached
        # session context, which is invalidated on every history write.
        sid = await DatabaseService.__map_session_id(session_id)
        his: History | None = await db.get_by(History, session_id=sid)
        return his

    @staticmethod
    async def __load_pull_requests(session_id: UUID) -> list[PullRequest]:
        sid = await DatabaseService.__map_session_id(session_id)
        pr: list[PullRequest] = await db.list_by(PullRequest, session_id=sid)
        return pr

    @staticmethod
    async def __create_status(
        session_id: UUID, status: SessionStatus, msg: str
    ) -> DbStatus:
        sid = await DatabaseService.__map_session_id(session_id)
        return await db.create(
            DbStatus,
            session_id=sid,
            status=status,
            message=msg,
        )

    @staticmethod
    async def create_session(
        session_id: UUID,
        user_id: str,
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
            await redis_client.set_json(
                _k_user_id(user_id), user_pk, ttl=_ttl(_TTL_FACTS)
            )
            await redis_client.set_json(
                _k_user_name(user_pk), user_id, ttl=_ttl(_TTL_FACTS)
            )

        session: Session = await db.create(Session, user_id=user_pk, uuid=session_id)
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

        # Write-through the write-once facts so the first read is a cache hit.
        # All rows are committed above, so these values match the DB.
        await redis_client.set_json(
            _k_sid(session_id), session.id, ttl=_ttl(_TTL_FACTS)
        )
        await redis_client.set_json(
            _k_workspace(session_id),
            {"uri": repo_uri, "branch": branch_name, "root_path": iac_path},
            ttl=_ttl(_TTL_FACTS),
        )
        await redis_client.set_json(
            _k_provider(session_id),
            {"provider": terraform_prv.value, "scope_id": scope_id},
            ttl=_ttl(_TTL_FACTS),
        )
        await redis_client.set_json(
            _k_first_query(session_id), query, ttl=_ttl(_TTL_FACTS)
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
            username: str | None = await DatabaseService.__map_user_name(
                session.user_id
            )
            assert username is not None
            workspace: WorkspaceFacts | None = await DatabaseService.__workspace_facts(
                session_id
            )
            if workspace is None:
                raise SessionTerminal(
                    message=f"Session {session_id} does not have a workspace",
                    error_code=404,
                )
            provider: ProviderFacts | None = await DatabaseService.__provider_facts(
                session_id
            )
            if provider is None:
                raise SessionTerminal(
                    message=f"Session {session_id} does not have an associated cloud provider",
                    error_code=404,
                )
            his: History | None = await DatabaseService.__load_history(session_id)
            ctx = SessionContext(
                id=session.uuid,
                user_id=username,
                repo_uri=workspace.uri,
                scope_id=provider.scope_id,
                terraform_prv=provider.provider,
                branch_name=workspace.branch,
                iac_path=workspace.root_path,
                history=his.payload if his else None,
            )
            return _serialize_ctx(ctx)

        data = await redis_client.get_or_set(
            _k_context(session_id), _ttl(_TTL_CONTEXT), _load
        )
        return _deserialize_ctx(data)

    @staticmethod
    async def list_sessions(
        user_id: str,
        order_by: str = "created_at",
        order_desc: bool = True,
        offset: int = 0,
        limit: int = 20,
    ) -> PaginatedSessionOverview:
        user_pk: int | None = await DatabaseService.__map_user_id(user_id)
        if user_pk is None:
            raise SessionTerminal(
                message=f"User {user_id} not found",
                error_code=404,
            )

        sessions, count = await db.query(
            Session,
            order_by=order_by,
            order_desc=order_desc,
            offset=offset,
            limit=limit,
            user_id=user_pk,
        )
        overviews: list[SessionOverview] = []
        for s in sessions:
            workspace: WorkspaceFacts | None = await DatabaseService.__workspace_facts(
                s.uuid
            )
            provider: ProviderFacts | None = await DatabaseService.__provider_facts(
                s.uuid
            )
            first_q: str | None = await DatabaseService.__first_query(s.uuid)
            if workspace is None or provider is None or first_q is None:
                raise SessionTerminal(
                    message=f"Session {s.uuid} is missconfigured",
                    error_code=500,
                )
            overviews.append(
                SessionOverview(
                    session_id=s.uuid,
                    first_query=first_q,
                    repo_uri=workspace.uri,
                    iac_path=workspace.root_path,
                    terraform_provider=provider.provider,
                    branch_name=workspace.branch,
                    is_blocked=s.is_blocked,
                    created_at=s.created_at,
                    updated_at=s.updated_at,
                )
            )

        return PaginatedSessionOverview(
            items=overviews,
            total=count,
            page=offset // limit,
            page_size=limit,
            total_pages=count // limit,
        )

    @staticmethod
    async def update_session(ctx: SessionContext) -> None:
        async with db.transaction() as sess:
            stmt = (
                update(History)
                .where(
                    Session.uuid == ctx.id,
                )
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
        _ = await redis_client.invalidate(_k_context(ctx.id))

    @staticmethod
    async def get_lock(session_id: UUID) -> Lock:
        """Cache-aside read of a session's concurrency lock state."""

        async def _load() -> dict[str, bool] | None:
            session: Session | None = await DatabaseService.__load_session(session_id)
            if session is None:
                return None
            return {"in_flight": session.in_flight, "is_blocked": session.is_blocked}

        data = await redis_client.get_or_set(
            _k_lock(session_id), _ttl(_TTL_LOCK), _load
        )
        if data is None:
            raise SessionTerminal(
                message=f"Session {session_id} not found.",
                error_code=404,
            )
        return Lock(**data)

    @staticmethod
    async def acquire_in_flight(session_id: UUID) -> None:
        """Atomic compare-and-set: True if we won the lock, False otherwise."""
        async with db.transaction() as sess:
            stmt = (
                update(Session)
                .where(
                    Session.uuid == session_id,
                )
                .values(in_flight=True, updated_at=datetime.now(timezone.utc))
            )
            res = await sess.execute(stmt)
            if cast(CursorResult[Any], res).rowcount != 1:
                raise SessionConflict(
                    message=f"Failed to acquire in-flight lock on session {session_id}.",
                    error_code=500,
                )
        # Lock state changed; drop the cached copy so the next read reloads.
        _ = await redis_client.invalidate(_k_lock(session_id))

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
        # Lock state changed; drop the cached copy so the next read reloads.
        _ = await redis_client.invalidate(_k_lock(session_id))

    @staticmethod
    async def mark_session_status(
        session_id: UUID, status: SessionStatus, msg: str
    ) -> None:
        _ = await DatabaseService.__create_status(session_id, status, msg)
        # A new row is now the most recent status; drop the cached one.
        _ = await redis_client.invalidate(_k_last_status(session_id))

    @staticmethod
    async def get_last_status(session_id: UUID) -> Status:
        async def _load() -> dict[str, str] | None:
            sid = await DatabaseService.__map_session_id(session_id)
            status_model = await db.list_by(
                model=DbStatus,
                order_by="created_at",
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
            _k_last_status(session_id), _ttl(_TTL_STATUS), _load
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
            # Lock state changed; drop the cached copy so the next read reloads.
            _ = await redis_client.invalidate(_k_lock(session_id))
        return updated

    @staticmethod
    async def get_pull_requests(session_id: UUID) -> list[PullRequest]:
        pr = await DatabaseService.__load_pull_requests(session_id)
        if len(pr) == 0:
            raise SessionTerminal(
                message=f"Session {session_id} does not have any associated Pull Requests ",
                error_code=404,
            )
        return pr
