# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import select, update

from src.infrastructure.database.database import db
from src.infrastructure.database.models import UserSession, SessionOperation


class DatabaseService:
    """Stateless static helpers over the `user_sessions` table."""

    @staticmethod
    async def start_session(
        *,
        session_id: UUID,
        user_id: str,
        repo_uri: str,
        cloud: str,
        environment: str,
        branch_name: str,
        operation_type: str = "generate",
        iac_path: str | None = None,
    ) -> UserSession:
        return await db.create(
            UserSession,
            session_id=str(session_id),
            user_id=user_id,
            repo_uri=repo_uri,
            cloud_provider=cloud,
            environment=environment,
            branch_name=branch_name,
            status="active",
            in_flight=False,
            history=[],
            last_payload=None,
            operation_type=operation_type,
            failure_reason=None,
            pull_request_url=None,
            apply_allowed=True,
            iac_path=iac_path,
        )

    @staticmethod
    async def load_session(session_id: str) -> Optional[UserSession]:
        return await db.get_by(UserSession, session_id=session_id)

    @staticmethod
    async def acquire_in_flight(session_id: str) -> bool:
        """Atomic compare-and-set: True if we won the lock, False otherwise."""
        async with db.transaction() as sess:
            stmt = (
                update(UserSession)
                .where(
                    UserSession.session_id == session_id,
                    UserSession.in_flight.is_(False),
                )
                .values(in_flight=True, updated_at=datetime.utcnow())
            )
            result = await sess.execute(stmt)
            return result.rowcount == 1

    @staticmethod
    async def release_in_flight(session_id: str) -> None:
        async with db.transaction() as sess:
            stmt = (
                update(UserSession)
                .where(UserSession.session_id == session_id)
                .values(in_flight=False, updated_at=datetime.utcnow())
            )
            await sess.execute(stmt)

    @staticmethod
    async def set_last_payload(session_id: str, payload: dict) -> None:
        async with db.transaction() as sess:
            stmt = (
                update(UserSession)
                .where(UserSession.session_id == session_id)
                .values(last_payload=payload, updated_at=datetime.utcnow())
            )
            await sess.execute(stmt)

    @staticmethod
    async def mark_completed(session_id: str) -> None:
        async with db.transaction() as sess:
            stmt = (
                update(UserSession)
                .where(UserSession.session_id == session_id)
                .values(status="completed", updated_at=datetime.utcnow())
            )
            await sess.execute(stmt)

    @staticmethod
    async def mark_failed(session_id: str, reason: str) -> None:
        """Record a failure reason without changing the session status.

        The session stays active so the user can retry. We just store the
        most recent error message for admin visibility.
        """
        async with db.transaction() as sess:
            stmt = (
                update(UserSession)
                .where(UserSession.session_id == session_id)
                .values(failure_reason=reason, updated_at=datetime.utcnow())
            )
            await sess.execute(stmt)

    @staticmethod
    async def set_pull_request_url(session_id: str, url: str) -> None:
        """Persist the URL of the PR created for this session."""
        async with db.transaction() as sess:
            stmt = (
                update(UserSession)
                .where(UserSession.session_id == session_id)
                .values(pull_request_url=url, updated_at=datetime.utcnow())
            )
            await sess.execute(stmt)

    @staticmethod
    async def set_apply_allowed(session_id: str, allowed: bool) -> None:
        """Set the apply_allowed flag (e.g. False when destructive changes detected)."""
        async with db.transaction() as sess:
            stmt = (
                update(UserSession)
                .where(UserSession.session_id == session_id)
                .values(apply_allowed=allowed, updated_at=datetime.utcnow())
            )
            await sess.execute(stmt)

    @staticmethod
    async def toggle_apply_allowed(session_id: str, allowed: bool) -> None:
        """Admin alias for set_apply_allowed — kept for back-compat."""
        await DatabaseService.set_apply_allowed(session_id, allowed)

    @staticmethod
    async def append_history(session_id: str, turn: dict) -> None:
        """Read-modify-write append. Safe under per-session in_flight guard."""
        async with db.transaction() as sess:
            stmt = select(UserSession).where(UserSession.session_id == session_id)
            row = (await sess.execute(stmt)).scalar_one()
            row.history = list(row.history) + [turn]
            row.updated_at = datetime.utcnow()

    @staticmethod
    async def get_session(session_id: str) -> Optional[UserSession]:
        # Back-compat alias used by remaining list/detail views.
        return await DatabaseService.load_session(session_id)

    @staticmethod
    async def list_sessions(
        search: str | None = None,
        status: str | None = None,
        order_by: str = "created_at",
        order_desc: bool = True,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[list[UserSession], int]:
        filters: dict[str, str] = {}
        if status:
            filters["status"] = status

        extra_conditions: list[Any] = []
        if search:
            pattern = f"%{search}%"
            extra_conditions.append(
                UserSession.user_id.ilike(pattern) | UserSession.repo_uri.ilike(pattern)
            )

        return await db.query(
            UserSession,
            filters=filters,
            extra_conditions=extra_conditions,
            order_by=order_by,
            order_desc=order_desc,
            offset=offset,
            limit=limit,
        )

    @staticmethod
    async def get_operation(
        session_id: str, operation_id: int
    ) -> SessionOperation | None:
        return await db.get_by(SessionOperation, session_id=session_id, id=operation_id)

    @staticmethod
    async def get_operations(
        session_id: str,
        order_by: str = "operation_number",
        order_desc: bool = False,
    ) -> list[SessionOperation]:
        return await db.list_by(
            SessionOperation,
            order_by=order_by,
            order_desc=order_desc,
            session_id=session_id,
        )
