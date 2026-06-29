# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Mapping is exposed as a passthrough on the core api.

The browser used to call the mapping service directly. It now goes
through core under /v1/mapping/resolve, which forwards to the
configured mapping microservice (or falls back to identity passthrough
when the service is disabled in system config).
"""

import unittest

from src.api.v1 import mapping
from src.infrastructure.external import mapping_service
from src.main import app


class TestMappingPassthroughWired(unittest.TestCase):
    def test_resolve_route_is_registered_on_app(self):
        paths = {route.path for route in app.routes}
        self.assertIn("/v1/mapping/resolve", paths)

    def test_endpoint_uses_mapping_service_client(self):
        self.assertIs(
            mapping.MappingServiceClient,
            mapping_service.MappingServiceClient,
        )
