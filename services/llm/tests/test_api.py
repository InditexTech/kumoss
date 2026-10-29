# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""HTTP-level tests for the LLM sidecar.

Cover the contract-visible behaviours: health, auth (missing / wrong /
right token, and the empty-token bypass), request validation, the
completion call shape and reply, the 502 / 500 problem mappings, and the
search 200 / 400 / 502 answers. LiteLLM's Router and search call and the
page reader are mocked; nothing reaches a provider or starts a browser.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient
from litellm.exceptions import APIError
from litellm.types.utils import (
    ChatCompletionMessageToolCall,
    Choices,
    Function,
    Message,
    ModelResponse,
    Usage,
)

from src import main as service_main
from src.completion_service import CompletionService
from src.config import Config, SearchConfig, SystemConfig


def _system(**web_search) -> SystemConfig:
    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "k"}):
        return SystemConfig(
            web_search=SearchConfig(**web_search) if web_search else SearchConfig()
        )


@contextmanager
def _client_with(
    token: str = "",
    router: MagicMock | None = None,
    system: SystemConfig | None = None,
    raise_server_exceptions: bool = True,
) -> Iterator[TestClient]:
    """Yield a TestClient with the service config (and Router) swapped in.

    The TestClient is entered as a context manager so the lifespan runs
    (building the real Router from the config); the Router is then
    replaced by the mock so no call leaves the process.
    """
    service_main.config = Config(expected_token=token, system=system or _system())
    with TestClient(
        service_main.app, raise_server_exceptions=raise_server_exceptions
    ) as client:
        if router is not None:
            service_main.app.state.completions = CompletionService(router)
        yield client


def _router(response: ModelResponse | None = None, error: Exception | None = None):
    router = MagicMock()
    router.acompletion = AsyncMock(return_value=response, side_effect=error)
    return router


def _model_response(**message_fields) -> ModelResponse:
    finish_reason = message_fields.pop("finish_reason", "stop")
    message_fields.setdefault("content", "hi there")
    return ModelResponse(
        model="claude-sonnet-5",
        choices=[
            Choices(
                index=0,
                message=Message(role="assistant", **message_fields),
                finish_reason=finish_reason,
            )
        ],
        usage=Usage(prompt_tokens=11, completion_tokens=22, total_tokens=33),
    )


_BODY = {
    "model": "anthropic/claude-sonnet-5",
    "messages": [
        {"role": "system", "content": "be helpful"},
        {"role": "user", "content": "hello"},
    ],
    "max_tokens": 32000,
    "temperature": 0.1,
    "num_retries": 3,
    "timeout": 600.0,
}


# --- health & auth -----------------------------------------------------------


def test_healthz_ok() -> None:
    with _client_with(token="secret") as client:
        for path in ("/v1/healthz", "/healthz"):
            response = client.get(path)
            assert response.status_code == 200
            assert response.json() == {"status": "ok"}


def test_lifespan_builds_the_router_from_the_config() -> None:
    with _client_with() as client:
        assert client  # lifespan ran
        router = service_main.app.state.completions._CompletionService__router
        assert sorted(router.get_model_names()) == [
            "anthropic/claude-haiku-4-5",
            "anthropic/claude-sonnet-5",
        ]


def test_endpoints_require_the_token_when_configured() -> None:
    with _client_with(
        token="expected-token", router=_router(_model_response())
    ) as client:
        for path, body in (("/v1/completions", _BODY), ("/v1/search", {"query": "q"})):
            response = client.post(path, json=body)
            assert response.status_code == 401
            assert response.headers["content-type"].startswith(
                "application/problem+json"
            )
            assert response.headers["WWW-Authenticate"] == "Bearer"
            assert (
                response.json()["title"] == "Missing or malformed bearer credentials."
            )


def test_wrong_token_is_rejected() -> None:
    with _client_with(
        token="expected-token", router=_router(_model_response())
    ) as client:
        response = client.post(
            "/v1/completions", headers={"Authorization": "Bearer wrong"}, json=_BODY
        )
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.json()["title"] == "Invalid bearer token."


def test_correct_token_is_accepted() -> None:
    with _client_with(
        token="expected-token", router=_router(_model_response())
    ) as client:
        response = client.post(
            "/v1/completions",
            headers={"Authorization": "Bearer expected-token"},
            json=_BODY,
        )
    assert response.status_code == 200


def test_empty_token_skips_the_check() -> None:
    with _client_with(token="", router=_router(_model_response())) as client:
        response = client.post("/v1/completions", json=_BODY)
    assert response.status_code == 200


# --- completions -------------------------------------------------------------


def test_completion_forwards_exactly_the_sent_kwargs() -> None:
    router = _router(_model_response())
    with _client_with(router=router) as client:
        response = client.post("/v1/completions", json=_BODY)

    assert response.status_code == 200
    router.acompletion.assert_awaited_once_with(**_BODY, drop_params=True)
    kwargs = router.acompletion.call_args.kwargs
    assert isinstance(kwargs["temperature"], float)
    assert isinstance(kwargs["timeout"], float)
    assert list(kwargs) == [
        "model",
        "messages",
        "max_tokens",
        "temperature",
        "num_retries",
        "timeout",
        "drop_params",
    ]


def test_completion_forwards_tools_and_reasoning_when_sent() -> None:
    tools = [
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read a file",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                },
            },
        }
    ]
    router = _router(_model_response())
    with _client_with(router=router) as client:
        client.post(
            "/v1/completions", json={**_BODY, "tools": tools, "tool_choice": "auto"}
        )
        router.acompletion.assert_awaited_with(
            **_BODY, tools=tools, tool_choice="auto", drop_params=True
        )
        client.post(
            "/v1/completions",
            json={**_BODY, "temperature": 1.0, "reasoning_effort": "low"},
        )
        router.acompletion.assert_awaited_with(
            **{**_BODY, "temperature": 1.0}, reasoning_effort="low", drop_params=True
        )


def test_null_optionals_stay_omitted_but_nested_nulls_survive() -> None:
    # An assistant tool-call turn carries `"content": null`; it must reach
    # LiteLLM untouched even though top-level null optionals are dropped.
    messages = [
        {"role": "user", "content": "search for test"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "grep_search", "arguments": '{"q": "test"}'},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": '{"success": true}'},
    ]
    router = _router(_model_response())
    body = {**_BODY, "messages": messages, "tools": None, "reasoning_effort": None}
    with _client_with(router=router) as client:
        response = client.post("/v1/completions", json=body)

    assert response.status_code == 200
    kwargs = router.acompletion.call_args.kwargs
    assert "tools" not in kwargs
    assert "reasoning_effort" not in kwargs
    assert kwargs["messages"] == messages


def test_completion_reply_shape() -> None:
    tc = ChatCompletionMessageToolCall(
        id="call_abc",
        type="function",
        function=Function(name="grep_search", arguments='{"query": "vault"}'),
    )
    router = _router(
        _model_response(
            content=None,
            tool_calls=[tc],
            finish_reason="tool_calls",
            reasoning_content="thinking...",
        )
    )
    with _client_with(router=router) as client:
        response = client.post("/v1/completions", json=_BODY)

    assert response.status_code == 200
    assert response.json() == {
        "text": "",
        "finish_reason": "tool_calls",
        "model": "claude-sonnet-5",
        "prompt_tokens": 11,
        "completion_tokens": 22,
        "tool_calls": [
            {"id": "call_abc", "name": "grep_search", "arguments": '{"query": "vault"}'}
        ],
        "reasoning_content": "thinking...",
        "model_name": "claude-sonnet-5",
        "llm_provider": "anthropic",
    }


def test_unresolvable_model_alias_gives_null_provider() -> None:
    with _client_with(router=_router(_model_response())) as client:
        response = client.post("/v1/completions", json={**_BODY, "model": "main"})
    payload = response.json()
    assert payload["model_name"] is None
    assert payload["llm_provider"] is None
    assert payload["reasoning_content"] is None


def test_provider_error_is_a_502_problem_with_the_status_code() -> None:
    error = APIError(
        message="service unavailable",
        model="claude-sonnet-5",
        llm_provider="anthropic",
        status_code=503,
    )
    with _client_with(router=_router(error=error)) as client:
        response = client.post("/v1/completions", json=_BODY)

    assert response.status_code == 502
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json() == {
        "type": "about:blank",
        "title": "Inference call failed",
        "status": 502,
        "detail": "Inference call to anthropic/claude-sonnet-5 failed.",
        "status_code": 503,
    }
    assert "service unavailable" not in response.text


def test_unexpected_error_is_a_500_problem() -> None:
    with _client_with(
        router=_router(error=ValueError("boom")), raise_server_exceptions=False
    ) as client:
        response = client.post("/v1/completions", json=_BODY)

    assert response.status_code == 500
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["title"] == "Internal server error"


def test_completion_validation_errors_are_422_problems() -> None:
    bad_bodies = [
        {k: v for k, v in _BODY.items() if k != "messages"},
        {**_BODY, "max_tokens": "lots"},
        {**_BODY, "unexpected": True},
        [],
    ]
    with _client_with(router=_router(_model_response())) as client:
        for body in bad_bodies:
            response = client.post("/v1/completions", json=body)
            assert response.status_code == 422, body
            assert response.headers["content-type"].startswith(
                "application/problem+json"
            )
            assert response.json()["status"] == 422


# --- search ------------------------------------------------------------------


def _reader(markdown: str) -> MagicMock:
    stub = MagicMock()
    ctx = stub.return_value
    ctx.__aenter__ = AsyncMock(return_value=ctx)
    ctx.__aexit__ = AsyncMock(return_value=False)
    ctx.read = AsyncMock(return_value=markdown)
    return stub


def test_search_returns_the_results() -> None:
    hit = MagicMock(title="T", url="https://a", snippet="s")
    with (
        _client_with(
            system=_system(provider="searxng", endpoint="http://searxng:8888")
        ) as client,
        patch(
            "src.search_service.litellm.asearch",
            AsyncMock(return_value=MagicMock(results=[hit])),
        ) as asearch,
        patch("src.search_service._PageReader", _reader("# page")),
    ):
        response = client.post("/v1/search", json={"query": "terraform s3"})

    assert response.status_code == 200
    assert response.json() == {
        "results": [{"title": "T", "url": "https://a", "content": "# page"}]
    }
    asearch.assert_awaited_once_with(
        query="terraform s3",
        max_results=5,
        search_provider="searxng",
        api_base="http://searxng:8888",
        timeout=30.0,
    )


def test_search_with_no_hits_is_an_empty_list() -> None:
    with (
        _client_with() as client,
        patch(
            "src.search_service.litellm.asearch",
            AsyncMock(return_value=MagicMock(results=[])),
        ),
    ):
        response = client.post("/v1/search", json={"query": "q"})
    assert response.status_code == 200
    assert response.json() == {"results": []}


def test_search_without_a_provider_is_a_400_problem() -> None:
    with _client_with(system=_system(provider="", endpoint="")) as client:
        response = client.post("/v1/search", json={"query": "q"})

    assert response.status_code == 400
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json() == {
        "type": "about:blank",
        "title": "Bad Request",
        "status": 400,
        "detail": "no search engine is configured (web_search.provider is empty in config.yaml)",
    }


def test_search_engine_failure_is_a_502_problem() -> None:
    with (
        _client_with(system=_system(provider="tavily", endpoint="")) as client,
        patch(
            "src.search_service.litellm.asearch",
            AsyncMock(side_effect=RuntimeError("secret token abc")),
        ),
    ):
        response = client.post("/v1/search", json={"query": "q"})

    assert response.status_code == 502
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json() == {
        "type": "about:blank",
        "title": "Bad Gateway",
        "status": 502,
        "detail": "the 'tavily' search engine call failed",
    }
    assert "abc" not in response.text


def test_search_validation_errors_are_422_problems() -> None:
    with _client_with() as client:
        for body in ({}, {"query": 3}, {"query": "q", "extra": 1}):
            response = client.post("/v1/search", json=body)
            assert response.status_code == 422, body
            assert response.headers["content-type"].startswith(
                "application/problem+json"
            )


def test_openapi_lists_the_contract_paths() -> None:
    with _client_with() as client:
        spec = json.loads(client.get("/openapi.json").text)
    assert {"/v1/healthz", "/v1/completions", "/v1/search"} <= set(spec["paths"])
