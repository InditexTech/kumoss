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
    SessionForbidden,
    SessionTerminal,
)
from src.infrastructure.database.database import db
from src.infrastructure.database.models import (
    CloudProvider,
    PullRequest,
    Status as DbStatus,
    User,
    Session,
    Workspace,
    History,
)
from src.shared.constants import SessionStatus, TemplateProvider
from src.shared.logger import logging
from src.shared.utils.decorators import async_cache


class DatabaseService:
    """Stateless static DB helpers."""

    @staticmethod
    async def __load_session(session_id: UUID) -> Session | None:
        session: Session | None = await db.get_by(Session, session_id=session_id)
        return session

    @staticmethod
    @async_cache
    async def __load_user(session_id: UUID) -> User | None:
        user: User | None = await db.get_by(User, session_id=session_id)
        return user

    @staticmethod
    async def __load_workspace(session_id: UUID) -> Workspace | None:
        workspace: Workspace | None = await db.get_by(Workspace, session_id=session_id)
        return workspace

    @staticmethod
    @async_cache
    async def __load_cloud(session_id: UUID) -> CloudProvider | None:
        cloud: CloudProvider | None = await db.get_by(
            CloudProvider, session_id=session_id
        )
        return cloud

    @staticmethod
    async def __load_pull_requests(session_id: UUID) -> list[PullRequest]:
        pr: list[PullRequest] = await db.list_by(PullRequest, session_id=session_id)
        return pr

    @staticmethod
    async def __create_status(
        session_id: UUID, status: SessionStatus, msg: str
    ) -> DbStatus:
        return await db.create(
            DbStatus,
            session_id=session_id,
            status=status,
            message=msg,
        )

    @staticmethod
    async def create_session(
        *,
        session_id: UUID,
        user_id: str,
        repo_uri: str,
        cloud: str,
        branch_name: str,
        query: str,
        iac_path: str | None = None,
    ) -> Session:
        user: User | None = await DatabaseService.__load_user(session_id)
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
            CloudProvider,
            session_id=session.id,
            name=TemplateProvider[cloud],
        )
        _ = await db.create(
            History,
            session_id=session.id,
            first_query=query,
        )
        return session

    @staticmethod
    async def create_pull_request(
        session_id: UUID, uri: str, branch: str, root_path: str
    ) -> PullRequest:
        return await db.create(
            PullRequest,
            session_id=session_id,
            uri=uri,
            branch=branch,
            root_path=root_path,
        )

    @staticmethod
    async def get_session_context(session_id: UUID) -> SessionContext:
        user: User | None = await DatabaseService.__load_user(session_id)
        if user is None:
            raise SessionForbidden(
                message=f"Session {session_id} belongs to a different user.",
                error_code=400,
            )
        session: Session | None = await DatabaseService.__load_session(session_id)
        if session is None:
            raise SessionTerminal(
                message=f"Session {session_id} not found.",
                error_code=404,
            )
        workspace: Workspace | None = await DatabaseService.__load_workspace(session_id)
        if workspace is None:
            raise SessionTerminal(
                message=f"Session {session_id} does not have a workspace",
                error_code=404,
            )
        cloud: CloudProvider | None = await DatabaseService.__load_cloud(session_id)
        if cloud is None:
            raise SessionTerminal(
                message=f"Session {session_id} does not have an associated cloud provider",
                error_code=404,
            )

        return SessionContext(
            id=session.uuid,
            user_id=user.username,
            repo_uri=workspace.uri,
            cloud=cloud.name,
            branch_name=workspace.branch,
            iac_path=workspace.root_path,
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
            if cast(CursorResult[Any], res).rowcount == 1:
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
            if cast(CursorResult[Any], res).rowcount == 1:
                raise SessionConflict(
                    message=f"Failed to release in-flight lock on session {session_id}.",
                    error_code=500,
                )

    @staticmethod
    async def mark_session_status(
        session_id: UUID, status: SessionStatus, msg: str
    ) -> None:
        async with db.transaction() as sess:
            stmt = (
                update(Status)
                .where(Session.uuid == session_id)
                .values(
                    status=status,
                    updated_at=datetime.now(timezone.utc),
                )
            )
            res = await sess.execute(stmt)
            if cast(CursorResult[Any], res).rowcount != 1:
                logging.error(
                    f"error `mark_session_status` transaction session {session_id} "
                )
        _ = await DatabaseService.__create_status(session_id, status, msg)

    @staticmethod
    async def get_last_status(session_id: UUID) -> Status:
        status_model = await db.list_by(
            DbStatus,
            order_by="created_at",
            order_desc=True,
            session_id=session_id,
            limit=1,
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
    async def set_lock(session_id: UUID, allowed: bool) -> bool:
        async with db.transaction() as sess:
            stmt = (
                update(Session)
                .where(Session.uuid == session_id)
                .values(is_blocked=allowed, updated_at=datetime.now(timezone.utc))
            )
            res = await sess.execute(stmt)
            return cast(CursorResult[Any], res).rowcount == 1

    @staticmethod
    async def list_sessions(
        search: str | None = None,
        status: str | None = None,
        order_by: str = "created_at",
        order_desc: bool = True,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[list[Session], int]:
        filters: dict[str, str] = {}
        if status:
            filters["status"] = status

        extra_conditions: list[Any] = []
        if search:
            pattern = f"%{search}%"
            extra_conditions.append(Session.uuid.ilike(pattern))

        return await db.query(
            Session,
            filters=filters,
            extra_conditions=extra_conditions,
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
