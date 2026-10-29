# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Pydantic models matching contracts/openapi/llm.v1.yaml.

Hand-written here rather than imported from a generated client because the
service implements the contract — it doesn't consume it. The shapes must
match the spec.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class CompletionRequest(BaseModel):
    """The exact kwargs the core's LiteLLM adapter used to build.

    ``messages`` and ``tools`` are OpenAI chat-completions payloads and are
    forwarded to LiteLLM verbatim (no re-shaping). The optional keys are
    forwarded only when present, mirroring the adapter, which added
    ``tools`` / ``tool_choice`` only with tools and ``reasoning_effort``
    only with thinking enabled.
    """

    model_config = ConfigDict(extra="forbid")

    model: str
    messages: list[dict[str, Any]]
    max_tokens: int
    temperature: float
    num_retries: int
    timeout: float
    tools: list[dict[str, Any]] | None = None
    tool_choice: str | dict[str, Any] | None = None
    reasoning_effort: str | None = None


class ToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str | None
    name: str | None
    # The raw JSON string the model produced; parsing it is the caller's job
    # (the core used to `json.loads` it), so a malformed one reaches it intact.
    arguments: str


class CompletionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    # Raw LiteLLM/OpenAI finish reason (`stop`, `length`, `tool_calls`,
    # `content_filter`, ...): mapping it is the caller's job.
    finish_reason: str | None
    model: str | None
    prompt_tokens: int
    completion_tokens: int
    tool_calls: list[ToolCall]
    reasoning_content: str | None
    # `litellm.get_llm_provider(request.model)`; null when it cannot resolve
    # the model (e.g. a `model_list` alias).
    model_name: str | None
    llm_provider: str | None


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str


class SearchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    url: str
    content: str


class SearchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    results: list[SearchResult]


class Health(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"]


class Problem(BaseModel):
    """RFC 7807 problem details."""

    model_config = ConfigDict(extra="allow")

    type: str = "about:blank"
    title: str
    status: int = Field(ge=100, le=599)
    detail: str | None = None
    instance: str | None = None
