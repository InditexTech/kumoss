# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Tests for the notifications facade, mocked at the service HTTP boundary."""

import json
import os
from unittest.mock import AsyncMock, patch
from uuid import UUID

import httpx
import pytest
import respx

from src.clients.notifications.models.notification_request_severity import (
    NotificationRequestSeverity,
)
from src.infrastructure.external.notification_service import (
    NotificationServiceClient,
)
from src.shared.config import system_config
from src.shared.config.system_config import ServiceConfig
from src.shared.constants import PanelRole

_ENDPOINT = "http://notifications:8080"
_NOTIFY_URL = f"{_ENDPOINT}/v1/notify"
_DELIVERY_ID = "4ceaf7e3-609b-4db3-bc15-90f07512ffc2"
_SESSION_ID = UUID("21434e55-fa1f-43c5-ab4a-ecafb4d3729e")
_STAFF = "src.infrastructure.external.notification_service.UserService.emails_with_panel_role"


@pytest.fixture
def enabled_service():
    cfg = ServiceConfig(
        enabled=True, endpoint=_ENDPOINT, token_env="TEST_NOTIF_TOKEN", timeout=5.0
    )
    with (
        patch.dict(os.environ, {"TEST_NOTIF_TOKEN": "t0k3n"}),
        patch.object(system_config.services, "notifications", cfg),
    ):
        yield cfg


@pytest.fixture
def disabled_service():
    cfg = ServiceConfig(enabled=False, endpoint=_ENDPOINT)
    with patch.object(system_config.services, "notifications", cfg):
        yield cfg


def _notify(**overrides):
    kwargs = dict(
        kind="support.user_question",
        severity=NotificationRequestSeverity.INFO,
        subject="hi",
        body="hello",
        audience=["ops@example.com"],
    )
    kwargs.update(overrides)
    return NotificationServiceClient.notify(**kwargs)


# --- notify -----------------------------------------------------------------


async def test_notify_posts_contract_payload_with_bearer(enabled_service):
    with respx.mock(assert_all_called=True) as router:
        route = router.post(_NOTIFY_URL).mock(
            return_value=httpx.Response(202, json={"delivery_id": _DELIVERY_ID})
        )
        delivery_id = await _notify()
    assert delivery_id == UUID(_DELIVERY_ID)
    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer t0k3n"
    assert json.loads(request.content) == {
        "kind": "support.user_question",
        "severity": "info",
        "subject": "hi",
        "body": "hello",
        "audience": ["ops@example.com"],
    }


async def test_notify_sends_links_and_context_when_given(enabled_service):
    with respx.mock(assert_all_called=True) as router:
        route = router.post(_NOTIFY_URL).mock(
            return_value=httpx.Response(202, json={"delivery_id": _DELIVERY_ID})
        )
        _ = await _notify(
            links=[("Open session", "https://nebula.example/s/1")],
            context={"cloud": "azure", "round": 2},
        )
    sent = json.loads(route.calls.last.request.content)
    assert sent["links"] == [
        {"label": "Open session", "url": "https://nebula.example/s/1"}
    ]
    assert sent["context"] == {"cloud": "azure", "round": 2}


async def test_notify_returns_none_when_disabled(disabled_service):
    with respx.mock(assert_all_called=False) as router:
        route = router.post(_NOTIFY_URL)
        assert await _notify() is None
    assert not route.called


async def test_notify_returns_none_when_service_rejects(enabled_service):
    with respx.mock(assert_all_called=True) as router:
        router.post(_NOTIFY_URL).mock(
            return_value=httpx.Response(
                401,
                json={"type": "about:blank", "title": "Unauthorized", "status": 401},
                headers={"content-type": "application/problem+json"},
            )
        )
        assert await _notify() is None


async def test_notify_returns_none_on_timeout(enabled_service):
    with respx.mock(assert_all_called=True) as router:
        router.post(_NOTIFY_URL).mock(side_effect=httpx.ReadTimeout("slow"))
        assert await _notify() is None


async def test_notify_returns_none_when_unreachable(enabled_service):
    with respx.mock(assert_all_called=True) as router:
        router.post(_NOTIFY_URL).mock(side_effect=httpx.ConnectError("boom"))
        assert await _notify() is None


# --- recipients -------------------------------------------------------------


async def test_recipients_are_panel_editors_and_above_plus_the_owner():
    staff = AsyncMock(return_value=["admin@example.com", "editor@example.com"])
    with patch(_STAFF, staff):
        audience = await NotificationServiceClient.recipients("owner@example.com")
    staff.assert_awaited_once_with(PanelRole.EDITOR)
    assert audience == ["admin@example.com", "editor@example.com", "owner@example.com"]


async def test_recipients_do_not_repeat_an_owner_who_is_staff():
    staff = AsyncMock(return_value=["owner@example.com", "editor@example.com"])
    with patch(_STAFF, staff):
        audience = await NotificationServiceClient.recipients("owner@example.com")
    assert audience == ["editor@example.com", "owner@example.com"]


async def test_recipients_without_an_owner_email_are_staff_only():
    staff = AsyncMock(return_value=["editor@example.com"])
    with patch(_STAFF, staff):
        assert await NotificationServiceClient.recipients(None) == [
            "editor@example.com"
        ]


async def test_recipients_fall_back_to_the_owner_when_lookup_fails():
    staff = AsyncMock(side_effect=RuntimeError("db down"))
    with patch(_STAFF, staff):
        audience = await NotificationServiceClient.recipients("owner@example.com")
    assert audience == ["owner@example.com"]


# --- semantic helpers -------------------------------------------------------


@pytest.fixture
def staff():
    with patch(_STAFF, AsyncMock(return_value=["ops@example.com"])):
        yield


async def _sent_by(helper, enabled_service):
    with respx.mock(assert_all_called=True) as router:
        route = router.post(_NOTIFY_URL).mock(
            return_value=httpx.Response(202, json={"delivery_id": _DELIVERY_ID})
        )
        await helper(_SESSION_ID, "owner@example.com", "the summary")
    return json.loads(route.calls.last.request.content)


async def test_compliance_failure_targets_staff_and_owner(enabled_service, staff):
    sent = await _sent_by(
        NotificationServiceClient.notify_compliance_failure, enabled_service
    )
    assert sent["kind"] == "iac.compliance.check_failed"
    assert sent["severity"] == "warning"
    assert str(_SESSION_ID) in sent["subject"]
    assert sent["body"] == "the summary"
    assert sent["audience"] == ["ops@example.com", "owner@example.com"]
    assert "context" not in sent


async def test_apply_failure_is_an_error(enabled_service, staff):
    sent = await _sent_by(
        NotificationServiceClient.notify_apply_failure, enabled_service
    )
    assert sent["kind"] == "iac.apply.failure"
    assert sent["severity"] == "error"
    assert sent["audience"] == ["ops@example.com", "owner@example.com"]


async def test_exception_failure_is_an_error(enabled_service, staff):
    sent = await _sent_by(
        NotificationServiceClient.notify_exception_failure, enabled_service
    )
    assert sent["kind"] == "system.exception.failure"
    assert sent["severity"] == "error"
    assert sent["audience"] == ["ops@example.com", "owner@example.com"]


async def test_helpers_never_raise(enabled_service):
    with (
        patch(_STAFF, AsyncMock(side_effect=RuntimeError("db down"))),
        respx.mock(assert_all_called=True) as router,
    ):
        router.post(_NOTIFY_URL).mock(side_effect=httpx.ConnectError("boom"))
        await NotificationServiceClient.notify_apply_failure(
            _SESSION_ID, "owner@example.com", "tofu apply exited 1"
        )
