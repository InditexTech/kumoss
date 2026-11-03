# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Tests for the unauthenticated GET /healthz probe."""

import unittest

from httpx import ASGITransport, AsyncClient

from src.main import app


class TestHealthz(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        )

    async def asyncTearDown(self):
        await self.client.aclose()

    async def test_returns_ok(self):
        resp = await self.client.get("/healthz")
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json(), {"status": "ok"})

    async def test_reachable_under_root_path(self):
        # nginx forwards /api/... unchanged; the app strips root_path "/api".
        resp = await self.client.get("/api/healthz")
        self.assertEqual(resp.status_code, 200, resp.text)
