# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Tests for the notifications facade, mocked at the sidecar HTTP boundary."""

import json
import os
from unittest.mock import patch
from uuid import UUID

import httpx
import pytest
import respx

from src.clients.notifications.models.notification_request_severity import (
    NotificationRequestSeverity,
)
from src.domains.entities.session import SessionContext
from src.infrastructure.external.notification_service import (
    NotificationServiceClient,
)
from src.shared.config import system_config
from src.shared.config.system_config import ServiceConfig
from src.shared.constants import OperationType, TerraformProvider
from src.shared.exceptions import ExceptionHandler

_ENDPOINT = "http://notifications:8080"
_NOTIFY_URL = f"{_ENDPOINT}/v1/notify"
_DELIVERY_ID = "4ceaf7e3-609b-4db3-bc15-90f07512ffc2"


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


def _send(**overrides):
    kwargs = dict(
        kind="support.user_question",
        severity=NotificationRequestSeverity.INFO,
        subject="hi",
        body="hello",
    )
    kwargs.update(overrides)
    return NotificationServiceClient.send(**kwargs)


async def test_send_posts_contract_payload_with_bearer(enabled_service):
    with respx.mock(assert_all_called=True) as router:
        route = router.post(_NOTIFY_URL).mock(
            return_value=httpx.Response(202, json={"delivery_id": _DELIVERY_ID})
        )
        accepted = await _send(
            audience=["a@example.com"],
            links=[("Session", "https://nebula.example/s/1")],
            context={"cloud": "azure"},
        )

    assert str(accepted.delivery_id) == _DELIVERY_ID
    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer t0k3n"
    sent = json.loads(request.content)
    assert sent == {
        "kind": "support.user_question",
        "severity": "info",
        "subject": "hi",
        "body": "hello",
        "audience": ["a@example.com"],
        "links": [{"label": "Session", "url": "https://nebula.example/s/1"}],
        "context": {"cloud": "azure"},
    }


async def test_send_omits_unset_optionals(enabled_service):
    with respx.mock(assert_all_called=True) as router:
        route = router.post(_NOTIFY_URL).mock(
            return_value=httpx.Response(202, json={"delivery_id": _DELIVERY_ID})
        )
        await _send()
    sent = json.loads(route.calls.last.request.content)
    assert set(sent) == {"kind", "severity", "subject", "body"}


async def test_send_disabled_raises_503(disabled_service):
    with pytest.raises(ExceptionHandler) as exc:
        await _send()
    assert exc.value.error_code == 503


async def test_send_relays_sidecar_503(enabled_service):
    problem = {
        "type": "about:blank",
        "title": "Service Unavailable",
        "status": 503,
        "detail": "no SLACK_WEBHOOK_URL is configured",
    }
    with respx.mock() as router:
        router.post(_NOTIFY_URL).mock(
            return_value=httpx.Response(
                503, json=problem, headers={"content-type": "application/problem+json"}
            )
        )
        with pytest.raises(ExceptionHandler) as exc:
            await _send()
    assert exc.value.error_code == 503
    assert "no SLACK_WEBHOOK_URL" in exc.value.message


async def test_send_maps_other_problems_to_502(enabled_service):
    problem = {"type": "about:blank", "title": "Invalid bearer token.", "status": 401}
    with respx.mock() as router:
        router.post(_NOTIFY_URL).mock(return_value=httpx.Response(401, json=problem))
        with pytest.raises(ExceptionHandler) as exc:
            await _send()
    assert exc.value.error_code == 502
    assert "Invalid bearer token" in exc.value.message


async def test_send_timeout_raises_504(enabled_service):
    with respx.mock() as router:
        router.post(_NOTIFY_URL).mock(side_effect=httpx.ReadTimeout("slow"))
        with pytest.raises(ExceptionHandler) as exc:
            await _send()
    assert exc.value.error_code == 504


async def test_send_unreachable_raises_502(enabled_service):
    with respx.mock() as router:
        router.post(_NOTIFY_URL).mock(side_effect=httpx.ConnectError("down"))
        with pytest.raises(ExceptionHandler) as exc:
            await _send()
    assert exc.value.error_code == 502


async def test_notify_swallows_failures(enabled_service):
    with respx.mock() as router:
        router.post(_NOTIFY_URL).mock(side_effect=httpx.ConnectError("down"))
        # Must not raise.
        await NotificationServiceClient.notify(
            kind="iac.apply.failure",
            severity=NotificationRequestSeverity.ERROR,
            subject="s",
            body="b",
        )


async def test_notify_noops_when_disabled(disabled_service):
    with respx.mock(assert_all_called=False) as router:
        route = router.post(_NOTIFY_URL)
        await NotificationServiceClient.notify(
            kind="iac.apply.failure",
            severity=NotificationRequestSeverity.ERROR,
            subject="s",
            body="b",
        )
    assert not route.called


def _session_ctx() -> SessionContext:
    return SessionContext(
        id=UUID("21434e55-fa1f-43c5-ab4a-ecafb4d3729e"),
        user_id="someone@example.com",
        round_id=2,
        repo_uri="https://github.com/org/infra.git",
        scope_id="demo-project",
        terraform_prv=TerraformProvider.AZURE,
        branch_name="nebula/21434e55",
        iac_path="envs/dev",
        operation_type=OperationType.GENERATE,
        history=[
            {"user": "Create a storage account in west europe", "assistant": "ok"},
            {"user": "Add a private endpoint", "assistant": "done"},
        ],
    )


def test_session_metadata_identifies_the_session():
    meta = NotificationServiceClient.session_metadata(_session_ctx())
    assert meta == {
        "session_id": "21434e55-fa1f-43c5-ab4a-ecafb4d3729e",
        "operation": "generate",
        "cloud": "azure",
        "project": "demo-project",
        "repository": "https://github.com/org/infra.git",
        "branch": "nebula/21434e55",
        "iac_path": "envs/dev",
        "round": 2,
        "user": "someone@example.com",
        "request": "Create a storage account in west europe",
    }


async def test_semantic_helpers_send_session_metadata_as_context(enabled_service):
    with respx.mock(assert_all_called=True) as router:
        route = router.post(_NOTIFY_URL).mock(
            return_value=httpx.Response(202, json={"delivery_id": _DELIVERY_ID})
        )
        await NotificationServiceClient.notify_apply_failure(
            _session_ctx(), "tofu apply exited 1"
        )
    sent = json.loads(route.calls.last.request.content)
    assert sent["kind"] == "iac.apply.failure"
    assert sent["severity"] == "error"
    assert "21434e55-fa1f-43c5-ab4a-ecafb4d3729e" in sent["subject"]
    assert sent["body"] == "tofu apply exited 1"
    assert sent["context"]["session_id"] == "21434e55-fa1f-43c5-ab4a-ecafb4d3729e"
    assert sent["context"]["request"] == "Create a storage account in west europe"
    assert sent["context"]["cloud"] == "azure"
