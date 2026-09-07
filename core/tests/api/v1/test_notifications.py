# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Tests for POST /v1/notifications (browser → core → notifications sidecar)."""

import unittest
from unittest.mock import AsyncMock, patch
from uuid import UUID

from fastapi.testclient import TestClient

from src.clients.notifications.models.notification_accepted import (
    NotificationAccepted,
)
from src.clients.notifications.models.notification_request_severity import (
    NotificationRequestSeverity,
)
from src.main import app
from src.shared.exceptions import ExceptionHandler

_SEND = "src.api.v1.notifications.NotificationServiceClient.send"
_DELIVERY_ID = UUID("8b5df7d0-c3dd-4db4-a93e-fdd5973be524")


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
        self.client = TestClient(app)

    def test_accepted_returns_202_with_delivery_id(self):
        send = AsyncMock(return_value=NotificationAccepted(delivery_id=_DELIVERY_ID))
        with patch(_SEND, send):
            resp = self.client.post("/v1/notifications", json=_payload())
        self.assertEqual(resp.status_code, 202)
        self.assertEqual(resp.json(), {"delivery_id": str(_DELIVERY_ID)})

    def test_forwards_full_contract_shape(self):
        send = AsyncMock(return_value=NotificationAccepted(delivery_id=_DELIVERY_ID))
        with patch(_SEND, send):
            resp = self.client.post(
                "/v1/notifications",
                json=_payload(
                    severity="warning",
                    audience=["someone@example.com"],
                    links=[{"label": "Session", "url": "https://nebula.example/s/1"}],
                    context={"cloud": "azure", "project": None},
                ),
            )
        self.assertEqual(resp.status_code, 202)
        kwargs = send.await_args.kwargs
        self.assertEqual(kwargs["kind"], "support.user_question")
        self.assertEqual(kwargs["severity"], NotificationRequestSeverity.WARNING)
        self.assertEqual(kwargs["audience"], ["someone@example.com"])
        self.assertEqual(kwargs["links"], [("Session", "https://nebula.example/s/1")])
        self.assertEqual(kwargs["context"], {"cloud": "azure", "project": None})

    def test_omitted_optionals_are_passed_as_none(self):
        send = AsyncMock(return_value=NotificationAccepted(delivery_id=_DELIVERY_ID))
        with patch(_SEND, send):
            self.client.post("/v1/notifications", json=_payload())
        kwargs = send.await_args.kwargs
        self.assertIsNone(kwargs["audience"])
        self.assertIsNone(kwargs["links"])
        self.assertIsNone(kwargs["context"])

    def test_service_unconfigured_returns_503(self):
        send = AsyncMock(side_effect=ExceptionHandler("no channel configured", 503))
        with patch(_SEND, send):
            resp = self.client.post("/v1/notifications", json=_payload())
        self.assertEqual(resp.status_code, 503)
        self.assertIn("no channel configured", resp.json()["detail"])

    def test_service_failure_returns_502(self):
        send = AsyncMock(side_effect=ExceptionHandler("unreachable", 502))
        with patch(_SEND, send):
            resp = self.client.post("/v1/notifications", json=_payload())
        self.assertEqual(resp.status_code, 502)

    def test_invalid_severity_returns_422_without_calling_service(self):
        send = AsyncMock()
        with patch(_SEND, send):
            resp = self.client.post("/v1/notifications", json=_payload(severity="loud"))
        self.assertEqual(resp.status_code, 422)
        send.assert_not_awaited()

    def test_unknown_field_rejected(self):
        send = AsyncMock()
        with patch(_SEND, send):
            resp = self.client.post("/v1/notifications", json=_payload(channel="#ops"))
        self.assertEqual(resp.status_code, 422)
        send.assert_not_awaited()

    def test_non_http_link_rejected(self):
        send = AsyncMock()
        with patch(_SEND, send):
            resp = self.client.post(
                "/v1/notifications",
                json=_payload(links=[{"label": "x", "url": "javascript:alert(1)"}]),
            )
        self.assertEqual(resp.status_code, 422)
        send.assert_not_awaited()
