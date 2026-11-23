# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import base64
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from opentelemetry.trace import Tracer

from src.infrastructure.telemetry import _initializer
from src.infrastructure.telemetry._initializer import get_tracer
from src.shared.config.system_config import TelemetryConfig


class TestExport(unittest.TestCase):
    def test_spans_go_to_the_langfuse_otlp_endpoint_with_the_key_pair(self):
        telemetry = TelemetryConfig(langfuse_url="https://langfuse.example.com")
        env = {"LANGFUSE_PUBLIC_KEY": "pk-lf-1", "LANGFUSE_SECRET_KEY": "sk-lf-2"}

        with (
            patch.dict("os.environ", env),
            patch.object(
                _initializer, "system_config", SimpleNamespace(telemetry=telemetry)
            ),
            patch.object(_initializer, "OTLPSpanExporter") as exporter,
        ):
            _ = _initializer._build_provider()  # pyright: ignore[reportPrivateUsage]

        token = base64.b64encode(b"pk-lf-1:sk-lf-2").decode()
        exporter.assert_called_once_with(
            endpoint="https://langfuse.example.com/api/public/otel/v1/traces",
            headers={"Authorization": f"Basic {token}"},
        )


class TestGetTracer(unittest.TestCase):
    def test_returns_otel_tracer(self):
        self.assertIsInstance(get_tracer(), Tracer)


if __name__ == "__main__":
    unittest.main()
