# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Service wiring tests: `iac` is mandatory, the other sidecars toggle."""

import os
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from src.shared.config.system_config import (
    IacServiceConfig,
    ServiceConfig,
    SystemConfig,
)

# Minimum env for SystemConfig to validate: the database URL, the LLM
# credentials and the mandatory iac bearer token.
BOOT_ENV = {
    "NEBULA_SQL_DATABASE_URL": "postgresql+asyncpg://test:test@localhost:5432/test",
    "OPENAI_API_KEY": "dummy",
    "NEBULA_IAC_TOKEN": "dummy-iac-token",
}

LLM = {"model": "openai/gpt-4o", "small_model": "openai/gpt-4o-mini"}


def _system_config(env: dict[str, str] | None = None, **data) -> SystemConfig:
    with patch.dict(os.environ, env if env is not None else BOOT_ENV, clear=True):
        return SystemConfig(llm=LLM, **data)


class TestIacServiceIsMandatory(unittest.TestCase):
    def test_iac_has_no_enabled_flag(self):
        self.assertFalse(hasattr(IacServiceConfig(), "enabled"))

    def test_stale_enabled_false_is_ignored(self):
        # Configs written before iac became mandatory may still carry the
        # key; it must not switch the service off.
        cfg = _system_config(services={"iac": {"enabled": False}})
        self.assertFalse(hasattr(cfg.services.iac, "enabled"))
        self.assertEqual(cfg.services.iac.endpoint, "http://iac:8082")

    def test_defaults_point_at_the_bundled_sidecar(self):
        cfg = IacServiceConfig()
        self.assertEqual(cfg.endpoint, "http://iac:8082")
        self.assertEqual(cfg.token_env, "NEBULA_IAC_TOKEN")

    def test_blank_endpoint_is_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            IacServiceConfig(endpoint="")
        self.assertIn("services.iac.endpoint is empty", str(ctx.exception))

    def test_missing_token_refuses_boot(self):
        env = {k: v for k, v in BOOT_ENV.items() if k != "NEBULA_IAC_TOKEN"}
        with self.assertRaises(ValidationError) as ctx:
            _system_config(env)
        self.assertIn("services.iac → $NEBULA_IAC_TOKEN", str(ctx.exception))

    def test_token_present_boots(self):
        # `token` reads the env at access time, so assert inside the patch.
        with patch.dict(os.environ, BOOT_ENV, clear=True):
            cfg = SystemConfig(llm=LLM)
            self.assertEqual(cfg.services.iac.token, "dummy-iac-token")


class TestOptionalServices(unittest.TestCase):
    def test_optional_sidecars_default_to_disabled(self):
        cfg = _system_config()
        self.assertFalse(cfg.services.notifications.enabled)
        self.assertFalse(cfg.services.mapping.enabled)
        self.assertFalse(cfg.services.authz.enabled)

    def test_disabled_sidecar_needs_no_token(self):
        # BOOT_ENV carries no NEBULA_MAPPING_TOKEN, and `clear=True` hides
        # any ambient one: boot must still succeed while mapping is off.
        with patch.dict(os.environ, BOOT_ENV, clear=True):
            cfg = SystemConfig(
                llm=LLM, services={"mapping": {"token_env": "NEBULA_MAPPING_TOKEN"}}
            )
            self.assertEqual(cfg.services.mapping.token, "")

    def test_enabled_sidecar_without_token_refuses_boot(self):
        with self.assertRaises(ValidationError) as ctx:
            _system_config(
                services={
                    "mapping": {
                        "enabled": True,
                        "token_env": "NEBULA_MAPPING_TOKEN",
                    }
                }
            )
        self.assertIn("services.mapping → $NEBULA_MAPPING_TOKEN", str(ctx.exception))

    def test_enabled_sidecar_with_token_boots(self):
        env = {**BOOT_ENV, "NEBULA_MAPPING_TOKEN": "dummy-mapping-token"}
        with patch.dict(os.environ, env, clear=True):
            cfg = SystemConfig(
                llm=LLM,
                services={
                    "mapping": {"enabled": True, "token_env": "NEBULA_MAPPING_TOKEN"}
                },
            )
            self.assertTrue(cfg.services.mapping.enabled)
            self.assertEqual(cfg.services.mapping.token, "dummy-mapping-token")

    def test_service_config_still_carries_enabled(self):
        self.assertTrue(ServiceConfig(enabled=True).enabled)


if __name__ == "__main__":
    unittest.main()
