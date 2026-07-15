# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from datetime import datetime, timezone
from typing import Any, cast
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.engine import CursorResult

from src.infrastructure.database.database import db
from src.infrastructure.database.models import (
    CloudProvider,
    Operation,
    PullRequest,
    User,
    Session,
    Workspace,
    History,
)
from src.shared.constants import SessionStatus, TemplateProvider


class DatabaseService:
    """Stateless static DB helpers."""

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
        user: User | None = await db.get_by(User, username=user_id)
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
    async def load_session(session_id: UUID) -> Session | None:
        return await db.get_by(Session, session_id=session_id)

    @staticmethod
    async def acquire_in_flight(session_id: UUID) -> bool:
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
            return cast(CursorResult[Any], res).rowcount == 1

    @staticmethod
    async def release_in_flight(session_id: UUID) -> bool:
        async with db.transaction() as sess:
            stmt = (
                update(Session)
                .where(Session.uuid == session_id)
                .values(in_flight=False, updated_at=datetime.now(timezone.utc))
            )
            res = await sess.execute(stmt)
            return cast(CursorResult[Any], res).rowcount == 1

    @staticmethod
    async def mark_completed(session_id: UUID) -> bool:
        async with db.transaction() as sess:
            stmt = (
                update(Session)
                .where(Session.uuid == session_id)
                .values(
                    status=SessionStatus.COMPLETED,
                    updated_at=datetime.now(timezone.utc),
                )
            )
            res = await sess.execute(stmt)
            return cast(CursorResult[Any], res).rowcount == 1

    @staticmethod
    async def mark_failed(session_id: UUID) -> bool:
        async with db.transaction() as sess:
            stmt = (
                update(Session)
                .where(Session.uuid == session_id)
                .values(
                    status=SessionStatus.FAILED,
                    updated_at=datetime.now(timezone.utc),
                )
            )
            res = await sess.execute(stmt)
            return cast(CursorResult[Any], res).rowcount == 1

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
    async def get_operation(session_id: UUID) -> Session | None:
        return await db.get_by(Session, session_id=session_id)

    @staticmethod
    async def get_operations(
        session_id: str,
        order_by: str = "operation_number",
        order_desc: bool = False,
    ) -> list[Operation]:
        return await db.list_by(
            Operation,
            order_by=order_by,
            order_desc=order_desc,
            session_id=session_id,
        )

    @staticmethod
    async def get_workspace(session_id: UUID) -> Workspace | None:
        return await db.get_by(Workspace, session_id=session_id)

    @staticmethod
    async def get_pull_requests(session_id: UUID) -> list[PullRequest]:
        return await db.list_by(PullRequest, session_id=session_id)
