# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""A sidecar disabled in system config is never contacted.

`services.<name>.enabled: false` (the checked-in default for mapping,
notifications and authz) must short-circuit inside the core: no HTTP
client is built, no request leaves the process, and — for the
notification helpers — no recipients lookup hits the database either.
Every generated `AuthenticatedClient` is patched to explode so any
attempt to reach the network fails the test loudly.
"""

from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest

from src.clients.notifications.models.notification_request_severity import (
    NotificationRequestSeverity,
)
from src.infrastructure.external import (
    authz_service,
    mapping_service,
    notification_service,
)
from src.shared.config import system_config
from src.shared.config.system_config import ServiceConfig

_SESSION_ID = UUID("21434e55-fa1f-43c5-ab4a-ecafb4d3729e")
_STAFF = "src.infrastructure.external.notification_service.UserService.emails_with_panel_role"


def _explode(*_args, **_kwargs):
    raise AssertionError("a disabled sidecar must never be contacted")


@pytest.fixture
def all_optional_sidecars_disabled():
    def disabled(port: int) -> ServiceConfig:
        return ServiceConfig(
            enabled=False, endpoint=f"http://svc:{port}", token_env="UNUSED_TOKEN"
        )

    with (
        patch.object(system_config.services, "mapping", disabled(8081)),
        patch.object(system_config.services, "notifications", disabled(8080)),
        patch.object(system_config.services, "authz", disabled(8083)),
        patch.object(mapping_service, "AuthenticatedClient", _explode),
        patch.object(notification_service, "AuthenticatedClient", _explode),
        patch.object(authz_service, "AuthenticatedClient", _explode),
    ):
        yield


# --- mapping ----------------------------------------------------------------


async def test_mapping_resolves_identifier_locally(all_optional_sidecars_disabled):
    ref = await mapping_service.MappingServiceClient().resolve(
        "https://github.com/me/my-iac.git", cloud="azure", environment="dev"
    )
    assert ref.repo_url == "https://github.com/me/my-iac.git"
    assert ref.project == "https://github.com/me/my-iac.git"
    assert ref.branch is None and ref.path is None


# --- authz ------------------------------------------------------------------


async def test_authz_check_answers_locally(all_optional_sidecars_disabled):
    result = await authz_service.AuthzServiceClient().check(
        cloud="azure", project="p", environment="dev", user_id="me@example.com"
    )
    assert result.authorized is True
    assert result.reason == "authz service disabled in system config"


async def test_authz_user_lookup_returns_none(all_optional_sidecars_disabled):
    client = authz_service.AuthzServiceClient()
    assert await client.get_current_user(user_id="me@example.com") is None
    assert await client.is_admin("me@example.com") is False


# --- notifications ----------------------------------------------------------


async def test_notify_returns_none(all_optional_sidecars_disabled):
    delivery_id = await notification_service.NotificationServiceClient.notify(
        kind="support.user_question",
        severity=NotificationRequestSeverity.INFO,
        subject="hi",
        body="hello",
        audience=["ops@example.com"],
    )
    assert delivery_id is None


@pytest.mark.parametrize(
    "helper",
    [
        notification_service.NotificationServiceClient.notify_compliance_failure,
        notification_service.NotificationServiceClient.notify_apply_failure,
        notification_service.NotificationServiceClient.notify_exception_failure,
    ],
)
async def test_notification_helpers_skip_recipients_lookup(
    all_optional_sidecars_disabled, helper
):
    with patch(_STAFF, AsyncMock(side_effect=_explode)) as staff:
        await helper(_SESSION_ID, "owner@example.com", "summary")
    staff.assert_not_called()
