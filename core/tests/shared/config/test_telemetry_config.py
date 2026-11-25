# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Langfuse connection settings.

The key pair falls back to the development keys the bundled compose
stack provisions, so the OSS stack boots without extra wiring. A config
still carrying the Phoenix ``collector_url`` is refused at boot instead
of being ignored, which would send traces to the default URL unnoticed.
"""

import os
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from src.shared.config.system_config import TelemetryConfig


class TestTelemetryConfig(unittest.TestCase):
    def test_without_env_the_bundled_stack_keys_are_used(self):
        with patch.dict(os.environ, {}, clear=True):
            config = TelemetryConfig()
            self.assertEqual(config.public_key, "pk-lf-kumoss-dev")
            self.assertEqual(config.secret_key, "sk-lf-kumoss-dev")
        self.assertEqual(config.langfuse_url, "http://langfuse-web:3000/")

    def test_the_env_vars_named_in_the_config_hold_the_keys(self):
        env = {"MY_PK": "pk-lf-real", "MY_SK": "sk-lf-real"}
        with patch.dict(os.environ, env):
            config = TelemetryConfig(public_key_env="MY_PK", secret_key_env="MY_SK")
            self.assertEqual(config.public_key, "pk-lf-real")
            self.assertEqual(config.secret_key, "sk-lf-real")

    def test_the_url_always_ends_in_a_slash(self):
        config = TelemetryConfig(langfuse_url="https://langfuse.example.com")
        self.assertEqual(config.langfuse_url, "https://langfuse.example.com/")

    def test_the_phoenix_collector_url_is_refused(self):
        with self.assertRaises(ValidationError) as ctx:
            _ = TelemetryConfig.model_validate(
                {"collector_url": "http://phoenix:6006/"}
            )
        self.assertIn("telemetry.langfuse_url", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
