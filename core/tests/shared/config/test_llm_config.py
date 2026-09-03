# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import os
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from src.shared.config.system_config import LlmConfig


class TestLlmConfigValidation(unittest.TestCase):
    def test_fail_fast_without_model_list(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValidationError) as ctx:
                LlmConfig(model="openai/gpt-4o", small_model="openai/gpt-4o-mini")
        self.assertIn("OPENAI_API_KEY", str(ctx.exception))

    def test_boots_when_default_env_vars_present(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "dummy"}, clear=True):
            config = LlmConfig(model="openai/gpt-4o", small_model="openai/gpt-4o-mini")
        self.assertEqual(config.model_list, [])

    def test_vertex_missing_keys_deduped(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValidationError) as ctx:
                LlmConfig(
                    model="vertex_ai/claude-sonnet-5",
                    small_model="vertex_ai/gemini-3.7-flash",
                )
        message = str(ctx.exception)
        self.assertEqual(message.count("VERTEXAI_PROJECT"), 1)
        self.assertEqual(message.count("VERTEXAI_LOCATION"), 1)

    def test_model_list_bypasses_scalar_validation(self):
        # The vertex role models would fail alone (no VERTEXAI_* set):
        # a non-empty model_list must be validated and routed instead.
        model_list = [
            {"model_name": "main", "litellm_params": {"model": "openai/gpt-4o"}}
        ]
        with patch.dict(os.environ, {"OPENAI_API_KEY": "dummy"}, clear=True):
            config = LlmConfig(
                model="vertex_ai/claude-sonnet-5",
                small_model="vertex_ai/gemini-3.7-flash",
                model_list=model_list,
            )
            router = config.create_router()
        self.assertEqual(router.get_model_names(), ["main"])


class TestLlmConfigCreateRouter(unittest.TestCase):
    def test_auto_generates_entry_per_role_model(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "dummy"}, clear=True):
            config = LlmConfig(model="openai/gpt-4o", small_model="openai/gpt-4o-mini")
            router = config.create_router()
        self.assertEqual(
            sorted(router.get_model_names()), ["openai/gpt-4o", "openai/gpt-4o-mini"]
        )
        self.assertEqual(
            sorted(entry["litellm_params"]["model"] for entry in router.model_list),
            ["openai/gpt-4o", "openai/gpt-4o-mini"],
        )

    def test_auto_generation_dedupes_identical_roles(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "dummy"}, clear=True):
            config = LlmConfig(model="openai/gpt-4o", small_model="openai/gpt-4o")
            router = config.create_router()
        self.assertEqual(router.get_model_names(), ["openai/gpt-4o"])


if __name__ == "__main__":
    unittest.main()
