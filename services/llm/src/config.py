# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Runtime configuration for the LLM sidecar.

Two sources, both resolved once at startup:

- The deployment's ``config.yaml`` — the SAME file the core reads, from
  the path in ``KUMOSS_CONFIG`` (default ``/etc/kumoss/config.yaml``). A
  missing path, or a directory in its place, means defaults. Only the
  ``llm`` and ``web_search`` sections are read; every other key belongs
  to the core and is ignored here.
- The environment: ``KUMOSS_LLM_TOKEN`` (the bearer token clients must
  present) and the LLM / search provider credentials LiteLLM reads.

``LlmConfig`` and ``SearchConfig`` are verbatim ports of the Python
core's models (``core/src/shared/config/system_config.py``): same
defaults, constraints, validators and error messages, including the
``litellm.validate_environment`` credential fail-fast. The section
container is named ``SystemConfig`` on purpose so validation errors read
``... validation error for SystemConfig`` exactly as the core's did.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import litellm
import yaml
from litellm.router import Router
from litellm.types.utils import SearchProviders
from pydantic import BaseModel, Field, model_validator


DEFAULT_CONFIG_PATH = "/etc/kumoss/config.yaml"


class ConfigError(ValueError):
    """Raised when the resolved system configuration is unusable.

    Surfaced at startup.
    """


class SearchConfig(BaseModel):
    """Web search backend used by the core's ``web_search`` tool.

    ``provider`` selects the LiteLLM search provider used for every
    ``web_search`` tool call (see ``litellm.types.utils.SearchProviders``:
    searxng, tavily, brave, perplexity, ...). It must be set: the tool has
    no LLM-native search fallback, so an empty provider disables web
    search entirely.

    ``endpoint`` is the base URL of the search service (``api_base``).
    Required for ``searxng``; optional (or unused) for hosted providers
    that read credentials from their standard env vars. ``timeout`` is the
    per-request HTTP budget in seconds — it covers both the search call
    and each individual page read — and ``max_results`` caps the number of
    results returned per query.

    ``max_page_chars`` truncates the readable text extracted from each
    result page. The tool's worst-case payload is ``max_results *
    max_page_chars`` characters of tool result, so raise it for richer
    source material at the cost of the calling agent's context.

    Two small-model inferences always stand between the pages and the
    agent — one summary per page, then a cross-page ranking — and only the
    top ``summarize_top`` summaries reach it, bounding a search's context
    cost at ``summarize_top * summarize_max_chars``. ``summarize_max_chars``
    caps each summary; too low and dense reference pages lose detail the
    agent cannot get back. Any summarizer failure degrades to the raw
    results.
    """

    provider: str = SearchProviders.SEARXNG.value
    endpoint: str = "http://localhost:8888"
    timeout: float = Field(default=30.0, gt=0)
    max_results: int = Field(default=5, ge=1, le=20)
    max_page_chars: int = Field(default=6000, ge=500, le=20000)
    summarize_top: int = Field(default=1, ge=1, le=10)
    summarize_max_chars: int = Field(default=4000, ge=500, le=20000)

    @model_validator(mode="after")
    def _assert_provider(self) -> "SearchConfig":
        if not self.provider:
            if self.endpoint:
                raise ConfigError(
                    "web_search.endpoint is set but web_search.provider is "
                    "empty; set web_search.provider (e.g. searxng) or clear "
                    "the endpoint to disable web search."
                )
            return self
        if self.provider not in {item.value for item in SearchProviders}:
            raise ConfigError(
                f"web_search.provider '{self.provider}' is not a LiteLLM "
                + "search provider; see litellm.types.utils.SearchProviders."
            )
        if self.provider == "searxng" and not self.endpoint:
            raise ConfigError(
                "web_search.provider 'searxng' requires web_search.endpoint "
                + "(the base URL of the SearXNG instance)."
            )
        return self


class LlmConfig(BaseModel):
    """LLM provider selection via LiteLLM Router.

    The core uses two model roles per workflow: ``model`` for high-quality
    reasoning and ``small_model`` for cheaper filler work.  Both are
    LiteLLM model-id strings (``provider/model``).  Credentials are
    resolved from the provider's standard env vars (see the provider
    tables at
    https://inditextech.github.io/kumoss/stable/main/reference/llm-providers/);
    the validator fails boot when litellm reports required env vars
    missing.

    ``temperature``, ``max_output_tokens`` and ``timeout`` apply to both
    roles. ``timeout`` is the per-request budget in seconds LiteLLM
    enforces on a single inference call (retries get a fresh budget);
    long reasoning or web-search calls need a generous value.

    ``model_list`` is an advanced escape hatch in the LiteLLM Router
    format (fallbacks, load balancing, custom credential env var names
    via ``os.environ/VAR_NAME``).  When non-empty it is passed to the
    Router verbatim, ``model`` / ``small_model`` must match its
    ``model_name`` entries, and boot validation runs against the listed
    entries instead of the two role models.

    Refer to https://docs.litellm.ai/docs/providers for provider-specific
    credential keys and to https://models.litellm.ai/ for model IDs.
    """

    model: str = "anthropic/claude-sonnet-5"
    small_model: str = "anthropic/claude-haiku-4-5"
    temperature: float = 0.1
    max_output_tokens: int = 32000
    timeout: float = Field(default=600.0, gt=0)

    model_list: list[dict[str, Any]] = Field(default_factory=list)

    def _effective_model_list(self) -> list[dict[str, Any]]:
        if self.model_list:
            return self.model_list
        return [
            {"model_name": model_id, "litellm_params": {"model": model_id}}
            for model_id in dict.fromkeys((self.model, self.small_model))
        ]

    @model_validator(mode="after")
    def _assert_llm_credentials(self) -> LlmConfig:
        """Fail-fast on env vars litellm requires for the configured models."""
        missing: list[str] = []
        for entry in self._effective_model_list():
            if litellm_params := entry.get("litellm_params", {}):
                model = litellm_params.get("model", "")
                result = litellm.validate_environment(model=model)

                if missing_keys := result.get("missing_keys"):
                    missing.extend(missing_keys)

        if missing := list(dict.fromkeys(missing)):
            raise ConfigError(
                "LLM credentials missing from environment: "
                + "; ".join(missing)
                + ". Set the listed env vars or configure llm.model_list in config.yaml."
            )
        return self

    def create_router(self) -> Router:
        return Router(model_list=self._effective_model_list())


class SystemConfig(BaseModel, frozen=True):
    """The slice of the core's ``config.yaml`` this sidecar owns.

    Field order matches the core's ``SystemConfig`` (``llm`` before
    ``web_search``) and unknown keys are ignored (pydantic's default), so
    the full core file validates here exactly as those two sections did
    in the core.
    """

    llm: LlmConfig = Field(default_factory=LlmConfig)
    web_search: SearchConfig = Field(default_factory=SearchConfig)

    @classmethod
    def load(cls, config_path: str = DEFAULT_CONFIG_PATH) -> SystemConfig:
        """Load from YAML if KUMOSS_CONFIG points at a real file; else defaults.

        We require the path to be an existing *file* (not a directory) before
        attempting to parse it. This guards against the docker-compose
        foot-gun where mounting a missing host file silently creates an
        empty directory on the container side.
        """
        path = os.environ.get("KUMOSS_CONFIG") or config_path
        if path and Path(path).is_file():
            with open(path) as f:
                data = yaml.safe_load(f) or {}
            return cls.model_validate(data)

        return cls()


@dataclass(frozen=True)
class Config:
    """Resolved at startup.

    - ``expected_token``: bearer token clients must present
      (``KUMOSS_LLM_TOKEN``). If unset, the service accepts any (or no)
      token (intended for local development).
    - ``system``: the validated ``llm`` / ``web_search`` sections.
    """

    expected_token: str
    system: SystemConfig

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            expected_token=os.environ.get("KUMOSS_LLM_TOKEN", ""),
            system=SystemConfig.load(),
        )
