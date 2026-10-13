# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Web search backend validation.

``SearchConfig`` wires the agents' ``web_search`` tool to a LiteLLM
search provider. The default (empty provider, empty endpoint) keeps the
LLM-native fallback and never fails; a named provider must be known to
LiteLLM, ``searxng`` must carry its endpoint, and a half-configured
endpoint without a provider is rejected at boot instead of being
silently ignored.
"""

import unittest

from pydantic import ValidationError

from src.shared.config.system_config import SearchConfig


def _search_providers() -> set[str]:
    from litellm.types.utils import SearchProviders

    return {item.value for item in SearchProviders}


class TestSearchConfigAccepts(unittest.TestCase):
    def test_defaults_use_the_llm_native_fallback(self):
        config = SearchConfig()
        self.assertEqual(config.provider, "")
        self.assertEqual(config.endpoint, "")
        self.assertEqual(config.timeout, 30.0)
        self.assertEqual(config.max_results, 10)

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


class TestSearchConfigRejects(unittest.TestCase):
    def test_unknown_provider_fails_boot(self):
        with self.assertRaises(ValidationError) as ctx:
            SearchConfig(provider="definitely-not-a-provider", endpoint="http://x")
        self.assertIn(
            "web_search.provider 'definitely-not-a-provider' is not a "
            "LiteLLM search provider",
            str(ctx.exception),
        )

    def test_searxng_requires_an_endpoint(self):
        with self.assertRaises(ValidationError) as ctx:
            SearchConfig(provider="searxng")
        self.assertIn(
            "web_search.provider 'searxng' requires web_search.endpoint",
            str(ctx.exception),
        )

    def test_endpoint_without_a_provider_is_rejected(self):
        # A half-configured state: silently ignoring the endpoint would
        # look like the engine is used while the LLM-native path runs.
        with self.assertRaises(ValidationError) as ctx:
            SearchConfig(endpoint="http://searxng:8888")
        self.assertIn(
            "web_search.endpoint is set but web_search.provider",
            str(ctx.exception),
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

    def test_timeout_must_be_positive(self):
        with self.assertRaises(ValidationError):
            SearchConfig(provider="searxng", endpoint="http://x", timeout=0.0)


if __name__ == "__main__":
    unittest.main()
