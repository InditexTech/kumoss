# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import unittest
from unittest.mock import patch

from opentelemetry.trace import Tracer

from src.infrastructure.telemetry._initializer import _active_project, get_tracer
from src.shared.constants import TracerProject


class TestActiveProject(unittest.TestCase):
    @patch("src.infrastructure.telemetry._initializer.system_config")
    def test_development_returns_dev(self, mock_config):
        mock_config.environment = "development"
        self.assertEqual(_active_project(), TracerProject.DEV_TERRAFORM_DAY2)

    @patch("src.infrastructure.telemetry._initializer.system_config")
    def test_staging_returns_pre(self, mock_config):
        mock_config.environment = "staging"
        self.assertEqual(_active_project(), TracerProject.PRE_TERRAFORM_DAY2)

    @patch("src.infrastructure.telemetry._initializer.system_config")
    def test_production_returns_pro(self, mock_config):
        mock_config.environment = "production"
        self.assertEqual(_active_project(), TracerProject.PRO_TERRAFORM_DAY2)

    @patch("src.infrastructure.telemetry._initializer.system_config")
    def test_unknown_environment_falls_through_to_pro(self, mock_config):
        mock_config.environment = "anything-else"
        self.assertEqual(_active_project(), TracerProject.PRO_TERRAFORM_DAY2)


class TestGetTracer(unittest.TestCase):
    def test_returns_otel_tracer(self):
        tracer = get_tracer()
        self.assertIsInstance(tracer, Tracer)


class TestLiteLLMInstrumentorRegistered(unittest.TestCase):
    def test_litellm_acompletion_is_instrumented(self):
        import litellm

        original_module = litellm.acompletion.__module__
        # The instrumentor wraps acompletion — the wrapper lives in the
        # openinference package, not in litellm itself.
        self.assertNotEqual(
            original_module,
            "litellm.main",
            "litellm.acompletion should be wrapped by the instrumentor",
        )


if __name__ == "__main__":
    unittest.main()
