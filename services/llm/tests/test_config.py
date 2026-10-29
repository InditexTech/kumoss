# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""``llm`` / ``web_search`` validation and ``config.yaml`` loading.

The validation cases are ported from the core's
``tests/shared/config/test_llm_config.py`` and ``test_search_config.py``
(the models are verbatim ports, so every case must hold unchanged). The
loader cases pin that the sidecar reads the core's own file: same path
resolution, same missing-file / directory fallback, other sections
ignored.
"""

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from pydantic import ValidationError

from src.config import Config, LlmConfig, SearchConfig, SystemConfig


def _search_providers() -> set[str]:
    from litellm.types.utils import SearchProviders

    return {item.value for item in SearchProviders}


# --- LlmConfig (ported) ------------------------------------------------------


class TestLlmConfigValidation(unittest.TestCase):
    def test_defaults(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "dummy"}, clear=True):
            config = LlmConfig()
        self.assertEqual(config.model, "anthropic/claude-sonnet-5")
        self.assertEqual(config.small_model, "anthropic/claude-haiku-4-5")
        self.assertEqual(config.temperature, 0.1)
        self.assertEqual(config.max_output_tokens, 32000)
        self.assertEqual(config.timeout, 600.0)
        self.assertEqual(config.model_list, [])

    def test_defaults_demand_the_anthropic_key(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValidationError) as ctx:
                LlmConfig()
        self.assertIn(
            "LLM credentials missing from environment: ANTHROPIC_API_KEY. Set the "
            "listed env vars or configure llm.model_list in config.yaml.",
            str(ctx.exception),
        )

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

    def test_model_list_entries_are_validated(self):
        model_list = [
            {"model_name": "main", "litellm_params": {"model": "openai/gpt-4o"}}
        ]
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValidationError) as ctx:
                LlmConfig(model="main", small_model="main", model_list=model_list)
        self.assertIn("OPENAI_API_KEY", str(ctx.exception))

    def test_timeout_must_be_positive(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "dummy"}, clear=True):
            with self.assertRaises(ValidationError):
                LlmConfig(timeout=0)


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

    def test_router_receives_the_effective_model_list(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "dummy"}, clear=True):
            config = LlmConfig(model="openai/gpt-4o", small_model="openai/gpt-4o-mini")
        with patch("src.config.Router") as router_cls:
            config.create_router()
        router_cls.assert_called_once_with(
            model_list=[
                {
                    "model_name": "openai/gpt-4o",
                    "litellm_params": {"model": "openai/gpt-4o"},
                },
                {
                    "model_name": "openai/gpt-4o-mini",
                    "litellm_params": {"model": "openai/gpt-4o-mini"},
                },
            ]
        )


# --- SearchConfig (ported) ---------------------------------------------------


class TestSearchConfigAccepts(unittest.TestCase):
    def test_defaults_point_at_a_local_searxng(self):
        config = SearchConfig()
        self.assertEqual(config.provider, "searxng")
        self.assertEqual(config.endpoint, "http://localhost:8888")
        self.assertEqual(config.timeout, 30.0)
        self.assertEqual(config.max_results, 5)
        self.assertEqual(config.max_page_chars, 6000)
        self.assertEqual(config.summarize_top, 1)
        self.assertEqual(config.summarize_max_chars, 4000)

    def test_accepts_searxng_with_an_endpoint(self):
        config = SearchConfig(provider="searxng", endpoint="http://searxng:8888")
        self.assertEqual(config.provider, "searxng")
        self.assertEqual(config.endpoint, "http://searxng:8888")

    def test_accepts_hosted_providers_without_an_endpoint(self):
        # Hosted providers read credentials from env vars; no endpoint needed.
        hosted = _search_providers() - {"searxng"}
        self.assertTrue(hosted)
        for provider in hosted:
            with self.subTest(provider=provider):
                config = SearchConfig(provider=provider)
                self.assertEqual(config.provider, provider)

    def test_provider_set_binds_the_field(self):
        self.assertEqual(SearchConfig(provider="tavily").provider, "tavily")

    def test_empty_provider_and_endpoint_disable_search(self):
        config = SearchConfig(provider="", endpoint="")
        self.assertEqual(config.provider, "")


class TestSearchConfigRejects(unittest.TestCase):
    def test_unknown_provider_fails_boot(self):
        with self.assertRaises(ValidationError) as ctx:
            SearchConfig(provider="definitely-not-a-provider", endpoint="http://x")
        self.assertIn(
            "web_search.provider 'definitely-not-a-provider' is not a "
            "LiteLLM search provider; see litellm.types.utils.SearchProviders.",
            str(ctx.exception),
        )

    def test_searxng_requires_an_endpoint(self):
        with self.assertRaises(ValidationError) as ctx:
            SearchConfig(provider="searxng", endpoint="")
        self.assertIn(
            "web_search.provider 'searxng' requires web_search.endpoint "
            "(the base URL of the SearXNG instance).",
            str(ctx.exception),
        )

    def test_endpoint_without_a_provider_is_rejected(self):
        # A half-configured state: silently ignoring the endpoint would
        # look like the engine is used while web search is in fact off.
        with self.assertRaises(ValidationError) as ctx:
            SearchConfig(provider="", endpoint="http://searxng:8888")
        self.assertIn(
            "web_search.endpoint is set but web_search.provider is empty; set "
            "web_search.provider (e.g. searxng) or clear the endpoint to "
            "disable web search.",
            str(ctx.exception),
        )

    def test_max_page_chars_out_of_bounds_fail(self):
        for max_page_chars in (499, 20_001):
            with self.subTest(max_page_chars=max_page_chars):
                with self.assertRaises(ValidationError):
                    SearchConfig(
                        provider="searxng",
                        endpoint="http://x",
                        max_page_chars=max_page_chars,
                    )

    def test_provider_with_surrounding_blanks_is_rejected(self):
        # No silent trimming: " searxng " is treated as an unknown
        # provider name rather than being coerced to `searxng`.
        with self.assertRaises(ValidationError) as ctx:
            SearchConfig(provider=" searxng ", endpoint="http://x")
        self.assertIn("is not a LiteLLM search provider", str(ctx.exception))

    def test_max_results_out_of_bounds_fail(self):
        for max_results in (0, 21):
            with self.subTest(max_results=max_results):
                with self.assertRaises(ValidationError):
                    SearchConfig(
                        provider="searxng", endpoint="http://x", max_results=max_results
                    )

    def test_summarize_bounds(self):
        for kwargs in (
            {"summarize_top": 0},
            {"summarize_top": 11},
            {"summarize_max_chars": 499},
            {"summarize_max_chars": 20_001},
        ):
            with self.subTest(**kwargs):
                with self.assertRaises(ValidationError):
                    SearchConfig(provider="searxng", endpoint="http://x", **kwargs)

    def test_timeout_must_be_positive(self):
        with self.assertRaises(ValidationError):
            SearchConfig(provider="searxng", endpoint="http://x", timeout=0.0)

    def test_timeout_must_be_a_number(self):
        with self.assertRaises(ValidationError):
            SearchConfig(provider="searxng", endpoint="http://x", timeout="soon")

    def test_max_results_boundaries_are_accepted(self):
        for max_results in (1, 20):
            with self.subTest(max_results=max_results):
                self.assertEqual(
                    SearchConfig(
                        provider="searxng",
                        endpoint="http://x",
                        max_results=max_results,
                    ).max_results,
                    max_results,
                )

    def test_hosted_provider_may_carry_an_endpoint(self):
        # The endpoint is only mandatory for `searxng`; hosted providers
        # are not forbidden from declaring one (e.g. a self-hosted
        # OpenAI-compatible search proxy).
        config = SearchConfig(provider="tavily", endpoint="http://proxy:9000")
        self.assertEqual(config.endpoint, "http://proxy:9000")


# --- config.yaml loading -----------------------------------------------------


_FULL_CORE_FILE = """\
environment: production
oidc:
  issuer_url: ""
services:
  iac:
    endpoint: http://iac:8082
storage:
  provider: NOT_A_REAL_PROVIDER   # core-only section: must be ignored here
llm:
  model: openai/gpt-4o
  small_model: openai/gpt-4o-mini
  temperature: 0.3
  timeout: 120
web_search:
  provider: tavily
  endpoint: ""
  max_results: 7
  max_page_chars: 1000
"""


class TestSystemConfigLoad(unittest.TestCase):
    def _write(self, tmp: str, text: str) -> str:
        path = Path(tmp) / "config.yaml"
        path.write_text(text)
        return str(path)

    def test_reads_only_the_llm_and_web_search_sections(self):
        with TemporaryDirectory() as tmp:
            path = self._write(tmp, _FULL_CORE_FILE)
            with patch.dict(
                os.environ, {"KUMOSS_CONFIG": path, "OPENAI_API_KEY": "k"}, clear=True
            ):
                config = SystemConfig.load()
        self.assertEqual(config.llm.model, "openai/gpt-4o")
        self.assertEqual(config.llm.temperature, 0.3)
        self.assertEqual(config.llm.timeout, 120.0)
        self.assertEqual(config.web_search.provider, "tavily")
        self.assertEqual(config.web_search.endpoint, "")
        self.assertEqual(config.web_search.max_results, 7)
        self.assertEqual(config.web_search.max_page_chars, 1000)
        self.assertFalse(hasattr(config, "storage"))

    def test_missing_file_means_defaults(self):
        with patch.dict(
            os.environ,
            {"KUMOSS_CONFIG": "/nonexistent/config.yaml", "ANTHROPIC_API_KEY": "k"},
            clear=True,
        ):
            config = SystemConfig.load()
        self.assertEqual(config, SystemConfig())

    def test_a_directory_in_place_of_the_file_means_defaults(self):
        # docker-compose creates an empty directory when the host file is
        # missing; that must read as "no config", not crash.
        with TemporaryDirectory() as tmp:
            with patch.dict(
                os.environ, {"KUMOSS_CONFIG": tmp, "ANTHROPIC_API_KEY": "k"}, clear=True
            ):
                config = SystemConfig.load()
        self.assertEqual(config.llm.model, "anthropic/claude-sonnet-5")

    def test_unset_env_falls_back_to_the_given_path(self):
        with TemporaryDirectory() as tmp:
            path = self._write(tmp, _FULL_CORE_FILE)
            with patch.dict(os.environ, {"OPENAI_API_KEY": "k"}, clear=True):
                config = SystemConfig.load(path)
        self.assertEqual(config.web_search.provider, "tavily")

    def test_empty_env_value_falls_back_to_the_given_path(self):
        with TemporaryDirectory() as tmp:
            path = self._write(tmp, _FULL_CORE_FILE)
            with patch.dict(
                os.environ, {"KUMOSS_CONFIG": "", "OPENAI_API_KEY": "k"}, clear=True
            ):
                config = SystemConfig.load(path)
        self.assertEqual(config.web_search.provider, "tavily")

    def test_empty_file_means_defaults(self):
        with TemporaryDirectory() as tmp:
            path = self._write(tmp, "")
            with patch.dict(
                os.environ,
                {"KUMOSS_CONFIG": path, "ANTHROPIC_API_KEY": "k"},
                clear=True,
            ):
                config = SystemConfig.load()
        self.assertEqual(config, SystemConfig())

    def test_errors_read_as_the_cores(self):
        with TemporaryDirectory() as tmp:
            path = self._write(tmp, "web_search:\n  provider: nope\n")
            with patch.dict(
                os.environ,
                {"KUMOSS_CONFIG": path, "ANTHROPIC_API_KEY": "k"},
                clear=True,
            ):
                with self.assertRaises(ValidationError) as ctx:
                    SystemConfig.load()
        message = str(ctx.exception)
        self.assertIn("1 validation error for SystemConfig", message)
        self.assertIn("web_search\n  Value error, web_search.provider 'nope'", message)

    def test_missing_credentials_fail_the_load(self):
        with TemporaryDirectory() as tmp:
            path = self._write(tmp, _FULL_CORE_FILE)
            with patch.dict(os.environ, {"KUMOSS_CONFIG": path}, clear=True):
                with self.assertRaises(ValidationError) as ctx:
                    SystemConfig.load()
        self.assertIn("OPENAI_API_KEY", str(ctx.exception))

    def test_the_config_is_frozen(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "k"}, clear=True):
            config = SystemConfig()
        with self.assertRaises(ValidationError):
            config.llm = LlmConfig()  # type: ignore[misc]


class TestConfigFromEnv(unittest.TestCase):
    def test_reads_the_token_and_the_file(self):
        with patch.dict(
            os.environ,
            {"KUMOSS_LLM_TOKEN": "t0k3n", "ANTHROPIC_API_KEY": "k"},
            clear=True,
        ):
            config = Config.from_env()
        self.assertEqual(config.expected_token, "t0k3n")
        self.assertEqual(config.system.web_search.provider, "searxng")

    def test_empty_token_is_allowed_for_local_dev(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "k"}, clear=True):
            config = Config.from_env()
        self.assertEqual(config.expected_token, "")


if __name__ == "__main__":
    unittest.main()
