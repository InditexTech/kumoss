# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Internal user resolution, provisioning, and role management."""

from typing import Any

from src.domains.entities import User
from src.domains.exceptions import UserAlreadyExists
from src.domains.services.database_service import DatabaseService
from src.domains.value_objects import TokenClaims
from src.shared.config.system_config import system_config
from src.shared.constants import OperationRole, PanelRole


# Identity used for every request while OIDC auth is disabled (blank
# issuer_url). Resolved into a real users row so session FKs and the
# admin panel work in local dev; always elevated to the top roles.
_DEV_CLAIMS = TokenClaims(
    issuer="urn:nebula:dev",
    subject="dev",
    email="dev@nebula.local",
    name="Local Developer",
    email_verified=True,
)


class UserService:
    """Identity resolution and role rules over the users store."""

    @staticmethod
    async def resolve(claims: TokenClaims | None = None) -> User:
        """Resolve token claims into the internal user, creating it on
        first login and syncing profile/elevation on every call."""
        if claims is None:
            claims = _DEV_CLAIMS
        user = await DatabaseService.get_user_by_identity(claims.issuer, claims.subject)
        if user is None:
            user = await UserService.__provision(claims)
        return await UserService.__sync_profile(user, claims)

    @staticmethod
    def __is_elevated(claims: TokenClaims) -> bool:
        if claims.issuer == _DEV_CLAIMS.issuer:
            return True
        if claims.email is None or not claims.email_verified:
            return False
        root = system_config.admin.default_root_email.strip().lower()
        return bool(root) and claims.email.lower() == root

    @staticmethod
    async def __provision(claims: TokenClaims) -> User:
        elevated = UserService.__is_elevated(claims)
        try:
            return await DatabaseService.create_user(
                issuer=claims.issuer,
                subject=claims.subject,
                email=claims.email,
                display_name=claims.name,
                operation_role=OperationRole.DEVOPS
                if elevated
                else OperationRole.DEVELOPER,
                panel_role=PanelRole.ADMIN if elevated else None,
            )
        except UserAlreadyExists:
            user = await DatabaseService.get_user_by_identity(
                claims.issuer, claims.subject
            )
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
        return await DatabaseService.update_user(user.id, values)

    @staticmethod
    async def list_users(
        offset: int = 0, limit: int = 20, search: str | None = None
    ) -> tuple[list[User], int]:
        return await DatabaseService.list_users(
            offset=offset, limit=limit, search=search
        )

    @staticmethod
    async def emails_with_panel_role(minimum: PanelRole) -> list[str]:
        """Emails of users holding ``minimum`` or a higher panel role."""
        return await DatabaseService.list_emails_with_panel_role(minimum)

    @staticmethod
    async def set_roles(
        user_id: int,
        operation_role: OperationRole,
        panel_role: PanelRole | None,
    ) -> User:
        return await DatabaseService.update_user(
            user_id, {"operation_role": operation_role, "panel_role": panel_role}
        )
