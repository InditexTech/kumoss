<!--
SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)

SPDX-License-Identifier: Apache-2.0
-->

# llm (bundled sidecar)

Reference implementation of [`contracts/openapi/llm.v1.yaml`](../../contracts/openapi/llm.v1.yaml).

The Kumoss core is written in Rust; the few pieces it needs that only
exist in the Python ecosystem live here, behind a small HTTP API:

- the **LiteLLM Router** — one multi-provider client for every chat
  completion the core makes (Anthropic, Vertex AI, Bedrock, OpenAI,
  on-prem OpenAI-compatible endpoints, ...);
- **LiteLLM web search** — the `web_search` tool's engine call
  (SearXNG, Tavily, Brave, Perplexity, ...);
- the **page reads** behind each search hit — headless Chromium
  (Playwright) renders the page, trafilatura reduces it to markdown.

The code is a straight port of the Python core's `LiteLLMAdapter`
(the LiteLLM call only), `SearchServiceClient`, and the `LlmConfig` /
`SearchConfig` models, so behaviour, limits, log lines and error
messages are unchanged. The core keeps prompt construction and reply
interpretation.

## What it does

- `POST /v1/completions` — runs
  `router.acompletion(**body, drop_params=True)` with exactly the keys
  sent (`model`, `messages`, `max_tokens`, `temperature`, `num_retries`,
  `timeout`, and only when present `tools`, `tool_choice`,
  `reasoning_effort`). Answers the first choice's text (`""` when null),
  the raw `finish_reason`, the served `model`, token usage (0 when the
  reply has none), tool calls with their raw `arguments` string, the
  `reasoning_content` when present, and the `model_name` /
  `llm_provider` that `litellm.get_llm_provider` resolves for the
  requested model (null when it cannot, e.g. a `model_list` alias).
  A provider failure (any `openai.OpenAIError`; every LiteLLM exception
  subclasses it) is logged as `LiteLLM API error: ...` and answered
  `502` with `detail` `Inference call to {model} failed.` and the
  provider's status in `status_code` (502 when it has none).
- `POST /v1/search` — `{"query": ...}` in, `{"results": [{title, url,
  content}]}` out. Calls `litellm.asearch` with the configured provider,
  endpoint (`api_base`, null when empty), `max_results` and `timeout`;
  keeps at most `max_results` hits (LiteLLM's SearXNG adapter ignores the
  cap); reads every hit's page concurrently in one shared headless
  Chromium, each bounded by `timeout` (navigation, then up to 5 s of
  `networkidle`); an HTTP status >= 400, a render error, no readable text
  or no url falls back to that hit's engine snippet; page text is cut to
  `max_page_chars`. No provider configured: `400` with `detail` `no search
  engine is configured (web_search.provider is empty in config.yaml)`.
  The engine call failing: `502` with `detail` `the '<provider>' search
  engine call failed` (the raw error is only logged).
- `GET /v1/healthz` (and `/healthz`) — liveness probe.
- Bearer-token auth on the `/v1/completions` and `/v1/search` endpoints
  when `KUMOSS_LLM_TOKEN` is set; otherwise any request is accepted
  (local-dev fallback). Tokens are compared in constant time.
- Every error is `application/problem+json` (RFC 7807): `401` bad
  token, `422` invalid body, `500` unexpected failure.

## Configuration

The service reads the **same `config.yaml` the core reads** (path from
`KUMOSS_CONFIG`, default `/etc/kumoss/config.yaml`; a missing file, or a
directory in its place, means built-in defaults) but only its `llm` and
`web_search` sections. Both are validated at startup exactly as the
Python core validated them: unknown search providers, `searxng` without
an endpoint, an endpoint without a provider, out-of-range limits, and
**missing provider credentials** (`litellm.validate_environment` for
every model in the effective model list) stop the process before it
serves anything. The LiteLLM Router is built once at startup from
`llm.model_list`, or from `llm.model` / `llm.small_model` when the list
is empty.

| Env var             | Required | Description                                                   |
|---------------------|----------|---------------------------------------------------------------|
| `KUMOSS_LLM_TOKEN`  | no       | Bearer token clients must present. Must match the core's.     |
| `KUMOSS_CONFIG`     | no       | Path of `config.yaml` (default `/etc/kumoss/config.yaml`).    |
| provider variables  | yes      | The LiteLLM credential env vars of the configured models (e.g. `ANTHROPIC_API_KEY`, `VERTEXAI_PROJECT` / `VERTEXAI_LOCATION` / `VERTEXAI_CREDENTIALS`) and of a hosted search provider (e.g. `TAVILY_API_KEY`). |

See [`env.sample`](env.sample).

### Behind a TLS-inspecting proxy

Same mechanism as the Python core image: the `host-certs` build context
supplies corporate roots at build time (Python index and Chromium
download), and at runtime the entrypoint merges any certificates mounted
at `KUMOSS_CA_DIR` (default `/usr/local/share/ca-certificates/host`) into
a bundle (`SSL_CERT_FILE`, `REQUESTS_CA_BUNDLE`, `NODE_EXTRA_CA_CERTS`)
and into Chromium's NSS database.

## Troubleshooting

- Container exits at boot with `LLM credentials missing from
  environment: ...`: set the listed variables in `services/llm/.env`.
- `401` at the core: `KUMOSS_LLM_TOKEN` differs between `core/.env` and
  `services/llm/.env`.
- `502` from `/v1/completions`: the provider rejected or failed the
  call; the service log carries the `LiteLLM API error: ...` line.
- Search results carrying only snippets: page reads are failing; the
  log has one `Page read for '<url>' failed, falling back to the engine
  snippet: ...` warning per hit with its cause (a
  `CERTIFICATE_VERIFY_FAILED` cause means the proxy roots are missing).

## Run locally

```bash
cd services/llm
uv sync
uv run playwright install chromium
ANTHROPIC_API_KEY=... KUMOSS_CONFIG=../../config.yaml \
  uv run uvicorn src.main:app --port 8090
```

## Run in docker compose

Copy `env.sample` to `.env` in this directory, set `KUMOSS_LLM_TOKEN`
(matching `core/.env`) and the provider credentials, and run
`docker compose up`.

## Tests

LiteLLM, Playwright and trafilatura are mocked; nothing reaches a
provider or starts a browser.

```bash
cd services/llm
uv sync --group tooling
uv run pytest
```
