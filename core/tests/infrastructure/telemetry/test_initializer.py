# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import unittest
from unittest.mock import patch

from opentelemetry.trace import Tracer

from src.infrastructure.telemetry._initializer import _route_tracer_project, get_tracer
from src.shared.constants import OperationType, TracerProject

_CONFIG = "src.infrastructure.telemetry._initializer.system_config"


class TestRouteTracerProject(unittest.TestCase):
    @patch(_CONFIG)
    def test_development_returns_dev(self, mock_config):
        mock_config.environment = "development"
        self.assertEqual(
            _route_tracer_project(OperationType.GENERATE),
            TracerProject.DEV_TERRAFORM_DAY2,
        )

    @patch(_CONFIG)
    def test_staging_returns_pre(self, mock_config):
        mock_config.environment = "staging"
        self.assertEqual(
            _route_tracer_project(OperationType.GENERATE),
            TracerProject.PRE_TERRAFORM_DAY2,
        )

    @patch(_CONFIG)
    def test_production_returns_pro(self, mock_config):
        mock_config.environment = "production"
        self.assertEqual(
            _route_tracer_project(OperationType.GENERATE),
            TracerProject.PRO_TERRAFORM_DAY2,
        )

    @patch(_CONFIG)
    def test_drift_routes_to_the_drift_project(self, mock_config):
        mock_config.environment = "production"
        self.assertEqual(
            _route_tracer_project(OperationType.DRIFT),
            TracerProject.PRO_TERRAFORM_DRIFT,
        )

    @patch(_CONFIG)
    def test_unknown_environment_raises(self, mock_config):
        mock_config.environment = "anything-else"
        with self.assertRaises(ValueError):
            _route_tracer_project(OperationType.GENERATE)


class TestGetTracer(unittest.TestCase):
    def test_returns_otel_tracer(self):
        tracer = get_tracer(OperationType.GENERATE)
        self.assertIsInstance(tracer, Tracer)


if __name__ == "__main__":
    unittest.main()
