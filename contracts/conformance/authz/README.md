<!--
SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)

SPDX-License-Identifier: Apache-2.0
-->

# authz conformance suite

Implementation-agnostic check that any service claiming to satisfy
[`contracts/openapi/authz.v1.yaml`](../../openapi/authz.v1.yaml)
actually does.

## Running

Point `--service-url` at any running implementation of the contract:

```bash
cd contracts/conformance/authz
uv sync
uv run pytest \
  --service-url=https://authz.your.example \
  --service-token=$YOUR_TOKEN
```

`--service-token` is only needed if the implementation enforces auth.
URL and token may also be supplied via `NEBULA_AUTHZ_URL` /
`NEBULA_AUTHZ_TOKEN`.

The bundled reference impl under `services/authz/` has its own test
suite — see that directory's README for how to run it.

## What this checks

- Every response the implementation returns conforms to the schema
  declared for its status code.
- Response bodies match the schemas declared in the OpenAPI spec,
  including for randomly generated invalid request bodies.

## What this does NOT check

- That 5xx responses are absent. The default `not_a_server_error` check
  is excluded, because the contract documents 5xx statuses (502 from a
  downstream backend); their bodies are still validated like any other
  response.
- Authorization semantics: whether a decision is *correct* is the
  implementation's own concern.

## Notes

- The suite drives the API as a black box; it does NOT exercise OIDC
  semantics (the contract assumes the caller — typically the core —
  has already validated OIDC). Identity comes in the `user_id` member
  of the `/v1/check` body, and via `X-User-Id` on the user endpoints.
- Admin endpoints are reachable only when the test caller has the
  `admin` role; without admin role assignments, those endpoints return
  the documented 403.
