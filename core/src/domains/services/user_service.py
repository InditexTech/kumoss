# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Internal user resolution, provisioning, and role management."""

from datetime import datetime, timezone
from typing import Any, cast

from sqlalchemy import func, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError

from src.domains.exceptions import UserNotFound
from src.infrastructure.auth.oidc import TokenClaims
from src.infrastructure.database.database import db
from src.infrastructure.database.models import User
from src.shared.config.system_config import system_config
from src.shared.constants import OperationRole, PanelRole

_DEV_ISSUER = "urn:nebula:dev"

# Identity used for every request while OIDC auth is disabled (blank
# issuer_url). Resolved into a real users row so session FKs and the
# admin panel work in local dev; always elevated to the top roles.
DEV_CLAIMS = TokenClaims(
    issuer=_DEV_ISSUER,
    subject="dev",
    email="dev@nebula.local",
    name="Local Developer",
)


class UserService:
    """Stateless static helpers over the users table."""

    @staticmethod
    async def resolve(claims: TokenClaims) -> User:
        """Resolve token claims into the internal user, creating it on
        first login and syncing profile/elevation on every call."""
        user: User | None = await db.get_by(
            User, issuer=claims.issuer, subject=claims.subject
        )
        if user is None:
            user = await UserService.__provision(claims)
        return await UserService.__sync_profile(user, claims)

    @staticmethod
    def __is_elevated(claims: TokenClaims) -> bool:
        if claims.issuer == _DEV_ISSUER:
            return True
        root = system_config.admin.default_root_email.strip().lower()
        return bool(root) and claims.email is not None and claims.email.lower() == root

    @staticmethod
    async def __provision(claims: TokenClaims) -> User:
        elevated = UserService.__is_elevated(claims)
        try:
            return await db.create(
                User,
                issuer=claims.issuer,
                subject=claims.subject,
                email=claims.email,
                display_name=claims.name,
                operation_role=OperationRole.DEVOPS
                if elevated
                else OperationRole.DEVELOPER,
                panel_role=PanelRole.ADMIN if elevated else None,
            )
        except IntegrityError:
            # Two parallel first requests: the loser of the (issuer,
            # subject) unique constraint re-reads the winner's row.
            user = await db.get_by(User, issuer=claims.issuer, subject=claims.subject)
            if user is None:
                raise
            return user

    @staticmethod
    async def __sync_profile(user: User, claims: TokenClaims) -> User:
        values: dict[str, Any] = {}
        if claims.email is not None and claims.email != user.email:
            values["email"] = claims.email
        if claims.name is not None and claims.name != user.display_name:
            values["display_name"] = claims.name
        if UserService.__is_elevated(claims):
            # Elevation is one-way: never demote an already-higher role.
            if user.operation_role is not OperationRole.DEVOPS:
                values["operation_role"] = OperationRole.DEVOPS
            if user.panel_role is not PanelRole.ADMIN:
                values["panel_role"] = PanelRole.ADMIN
        if not values:
            return user
        async with db.transaction() as sess:
            _ = await sess.execute(
                update(User)
                .where(User.id == user.id)
                .values(**values, updated_at=datetime.now(timezone.utc))
            )
        refreshed = await db.get_by(User, id=user.id)
        return refreshed if refreshed is not None else user

    @staticmethod
    async def list_users(
        offset: int = 0, limit: int = 20, search: str | None = None
    ) -> tuple[list[User], int]:
        async with db.session() as sess:
            stmt = select(User)
            if search:
                pattern = f"%{search}%"
                stmt = stmt.where(
                    or_(User.email.ilike(pattern), User.display_name.ilike(pattern))
                )
            count_stmt = select(func.count()).select_from(stmt.subquery())
            count: int = (await sess.execute(count_stmt)).scalar_one()
            stmt = stmt.order_by(User.created_at.desc()).offset(offset).limit(limit)
            users = list((await sess.execute(stmt)).scalars().all())
        return users, count

    @staticmethod
    async def set_roles(
        user_id: int,
        operation_role: OperationRole,
        panel_role: PanelRole | None,
    ) -> User:
        async with db.transaction() as sess:
            res = await sess.execute(
                update(User)
                .where(User.id == user_id)
                .values(
                    operation_role=operation_role,
                    panel_role=panel_role,
                    updated_at=datetime.now(timezone.utc),
                )
            )
            if cast(CursorResult[Any], res).rowcount != 1:
                raise UserNotFound(f"User {user_id} not found", 404)
        user = await db.get_by(User, id=user_id)
        if user is None:
            raise UserNotFound(f"User {user_id} not found", 404)
        return user
