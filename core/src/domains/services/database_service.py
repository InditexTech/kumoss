# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from datetime import datetime, timezone
from typing import Any, cast
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.engine import CursorResult


from src.domains.entities import SessionContext, Status
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
from src.shared.constants import SessionStatus, TerraformProvider
from src.shared.utils.decorators import async_cache


class DatabaseService:
    """Stateless static DB helpers."""

    @staticmethod
    @async_cache
    async def __map_session_id(uuid: UUID) -> int | None:
        session: Session | None = await db.get_by(Session, uuid=uuid)
        return session.id if session is not None else None

    @staticmethod
    async def __load_session(uuid: UUID) -> Session | None:
        session: Session | None = await db.get_by(Session, uuid=uuid)
        return session

    @staticmethod
    @async_cache
    async def __load_user_by_pk(pk: int) -> User | None:
        user: User | None = await db.get_by(User, id=pk)
        return user

    @staticmethod
    @async_cache
    async def __load_user_by_username(username: str) -> User | None:
        user: User | None = await db.get_by(User, username=username)
        return user

    @staticmethod
    @async_cache
    async def __load_workspace(session_id: UUID) -> Workspace | None:
        sid = await DatabaseService.__map_session_id(session_id)
        workspace: Workspace | None = await db.get_by(Workspace, session_id=sid)
        return workspace

    @staticmethod
    @async_cache
    async def __load_terraform_provider(session_id: UUID) -> DbTerraformProvider | None:
        sid = await DatabaseService.__map_session_id(session_id)
        tp: DbTerraformProvider | None = await db.get_by(
            DbTerraformProvider, session_id=sid
        )
        return tp

    @staticmethod
    async def __load_history(session_id: UUID) -> History | None:
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
        user: User | None = await DatabaseService.__load_user_by_username(user_id)
        if not user:
            user = await db.create(User, username=user_id)
        session: Session = await db.create(Session, user_id=user.id, uuid=session_id)
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
        return session

    @staticmethod
    async def get_session_context(session_id: UUID) -> SessionContext:
        session: Session | None = await DatabaseService.__load_session(session_id)
        if session is None:
            raise SessionTerminal(
                message=f"Session {session_id} not found.",
                error_code=404,
            )
        user: User | None = await DatabaseService.__load_user_by_pk(session.user_id)
        assert user is not None
        workspace: Workspace | None = await DatabaseService.__load_workspace(session_id)
        if workspace is None:
            raise SessionTerminal(
                message=f"Session {session_id} does not have a workspace",
                error_code=404,
            )
        terraform_prv: (
            DbTerraformProvider | None
        ) = await DatabaseService.__load_terraform_provider(session_id)
        if terraform_prv is None:
            raise SessionTerminal(
                message=f"Session {session_id} does not have an associated cloud provider",
                error_code=404,
            )
        his: History | None = await DatabaseService.__load_history(session_id)
        return SessionContext(
            id=session.uuid,
            user_id=user.username,
            repo_uri=workspace.uri,
            scope_id=terraform_prv.scope_id,
            terraform_prv=terraform_prv.provider,
            branch_name=workspace.branch,
            iac_path=workspace.root_path,
            is_blocked=session.is_blocked,
            created_at=session.created_at,
            updated_at=session.updated_at,
            history=his.payload if his else None,
        )

    @staticmethod
    async def update_session(ctx: SessionContext) -> None:
        sid = await DatabaseService.__map_session_id(ctx.id)
        async with db.transaction() as sess:
            stmt = (
                update(History)
                .where(
                    Session.uuid == sid,
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
        session_id: UUID, status: SessionStatus, msg: str
    ) -> None:
        # sid = await DatabaseService.__map_session_id(session_id)
        # async with db.transaction() as sess:
        #     stmt = (
        #         update(Status)
        #         .where(Session.uuid == sid)
        #         .values(
        #             status=status,
        #             updated_at=datetime.now(timezone.utc),
        #         )
        #     )
        #     res = await sess.execute(stmt)
        #     if cast(CursorResult[Any], res).rowcount != 1:
        #         logging.error(
        #             f"error `mark_session_status` transaction session {session_id} "
        #         )
        _ = await DatabaseService.__create_status(session_id, status, msg)

    @staticmethod
    async def get_last_status(session_id: UUID) -> Status:
        sid = await DatabaseService.__map_session_id(session_id)
        status_model = await db.list_by(
            model=DbStatus,
            order_by="created_at",
            order_desc=True,
            limit=1,
            session_id=sid,
        )
        if len(status_model) != 1:
            raise LastStatusError(f"No status records for session {session_id}", 500)
        return Status(status_model[0].status, status_model[0].message)

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
            return cast(CursorResult[Any], res).rowcount == 1

    @staticmethod
    async def list_sessions(
        order_by: str = "created_at",
        order_desc: bool = True,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[list[Session], int]:
        return await db.__query(  # FIXME
            Session,
            order_by=order_by,
            order_desc=order_desc,
            offset=offset,
            limit=limit,
        )

    @staticmethod
    async def get_pull_requests(session_id: UUID) -> list[PullRequest]:
        pr = await DatabaseService.__load_pull_requests(session_id)
        if len(pr) == 0:
            raise SessionTerminal(
                message=f"Session {session_id} does not have any associated Pull Requests ",
                error_code=404,
            )
        return pr
