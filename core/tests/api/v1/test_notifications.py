# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Tests for POST /v1/notifications (browser → core → notifications service).

The caller is injected through the auth dependency override; the facade
is mocked so only the route's own behaviour (validation, server-derived
audience, status mapping) is under test.
"""

import os
import unittest
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch
from uuid import UUID

from fastapi.testclient import TestClient

from src.api.deps import get_current_user
from src.clients.notifications.models.notification_request_severity import (
    NotificationRequestSeverity,
)
from src.domains.entities import User
from src.main import app
from src.shared.config import system_config
from src.shared.config.system_config import ServiceConfig
from src.shared.constants import OperationRole

_NOTIFY = "src.api.v1.notifications.NotificationServiceClient.notify"
_RECIPIENTS = "src.api.v1.notifications.NotificationServiceClient.recipients"
_DELIVERY_ID = UUID("8b5df7d0-c3dd-4db4-a93e-fdd5973be524")
_RECIPIENT_LIST = ["ops@example.com", "someone@example.com"]

_CALLER = User(
    id=7,
    issuer="urn:test",
    subject="sub-7",
    email="someone@example.com",
    display_name="Someone",
    operation_role=OperationRole.DEVELOPER,
    panel_role=None,
    created_at=datetime.now(UTC),
)


def _payload(**overrides):
    body = {
        "kind": "support.user_question",
        "severity": "info",
        "subject": "Support request from someone@example.com",
        "body": "How do I import an existing resource group?",
    }
    body.update(overrides)
    return body


class TestSubmitNotification(unittest.TestCase):
    def setUp(self):
        app.dependency_overrides[get_current_user] = lambda: _CALLER
        self.client = TestClient(app)
        cfg = ServiceConfig(
            enabled=True,
            endpoint="http://notifications:8080",
            token_env="TEST_NOTIF_TOKEN",
        )
        self._patches = [
            patch.dict(os.environ, {"TEST_NOTIF_TOKEN": "t0k3n"}),
            patch.object(system_config.services, "notifications", cfg),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in reversed(self._patches):
            p.stop()
        app.dependency_overrides.clear()

    def _post(self, notify=None, recipients=None, **overrides):
        notify = notify or AsyncMock(return_value=_DELIVERY_ID)
        recipients = recipients or AsyncMock(return_value=list(_RECIPIENT_LIST))
        with patch(_NOTIFY, notify), patch(_RECIPIENTS, recipients):
            resp = self.client.post("/v1/notifications", json=_payload(**overrides))
        return resp, notify, recipients

    def test_accepted_returns_202_with_delivery_id(self):
        resp, _, _ = self._post()
        self.assertEqual(resp.status_code, 202, resp.text)
        self.assertEqual(resp.json(), {"delivery_id": str(_DELIVERY_ID)})

    def test_audience_is_derived_from_the_caller(self):
        _, notify, recipients = self._post()
        recipients.assert_awaited_once_with("someone@example.com")
        self.assertEqual(notify.await_args.kwargs["audience"], _RECIPIENT_LIST)

    def test_client_supplied_audience_is_rejected(self):
        resp, notify, _ = self._post(audience=["anyone@example.com"])
        self.assertEqual(resp.status_code, 422)
        notify.assert_not_awaited()

    def test_forwards_severity_links_and_context(self):
        resp, notify, _ = self._post(
            severity="warning",
            links=[{"label": "Session", "url": "https://kumoss.example/s/1"}],
            context={"cloud": "azure", "project": None},
        )
        self.assertEqual(resp.status_code, 202, resp.text)
        kwargs = notify.await_args.kwargs
        self.assertEqual(kwargs["kind"], "support.user_question")
        self.assertEqual(kwargs["severity"], NotificationRequestSeverity.WARNING)
        self.assertEqual(kwargs["subject"], "Support request from someone@example.com")
        self.assertEqual(kwargs["body"], "How do I import an existing resource group?")
        self.assertEqual(kwargs["links"], [("Session", "https://kumoss.example/s/1")])
        self.assertEqual(kwargs["context"], {"cloud": "azure", "project": None})

    def test_omitted_optionals_are_passed_as_none(self):
        _, notify, _ = self._post()
        kwargs = notify.await_args.kwargs
        self.assertIsNone(kwargs["links"])
        self.assertIsNone(kwargs["context"])

    def test_not_delivered_returns_502(self):
        resp, _, _ = self._post(notify=AsyncMock(return_value=None))
        self.assertEqual(resp.status_code, 502)
        self.assertIn("not delivered", resp.json()["detail"])

    def test_disabled_service_returns_503_without_calling_it(self):
        with patch.object(
            system_config.services, "notifications", ServiceConfig(enabled=False)
        ):
            resp, notify, _ = self._post()
        self.assertEqual(resp.status_code, 503)
        notify.assert_not_awaited()

    def test_invalid_severity_returns_422_without_calling_service(self):
        resp, notify, _ = self._post(severity="loud")
        self.assertEqual(resp.status_code, 422)
        notify.assert_not_awaited()

    def test_unknown_field_rejected(self):
        resp, notify, _ = self._post(channel="#ops")
        self.assertEqual(resp.status_code, 422)
        notify.assert_not_awaited()

    def test_non_http_link_rejected(self):
        resp, notify, _ = self._post(
            links=[{"label": "x", "url": "javascript:alert(1)"}]
        )
        self.assertEqual(resp.status_code, 422)
        notify.assert_not_awaited()

    def test_requires_authentication(self):
        app.dependency_overrides.clear()
        with patch("src.api.deps._oidc_enabled", return_value=True):
            resp, notify, _ = self._post()
        self.assertEqual(resp.status_code, 401, resp.text)
        notify.assert_not_awaited()
