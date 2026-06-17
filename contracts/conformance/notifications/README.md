<!--
SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)

SPDX-License-Identifier: Apache-2.0
-->

# notifications conformance suite

Implementation-agnostic check that any service claiming to satisfy
[`contracts/openapi/notifications.v1.yaml`](../../openapi/notifications.v1.yaml)
actually does.

The suite uses [Schemathesis](https://schemathesis.readthedocs.io/) to
generate requests from the OpenAPI spec and verify that responses match
what the spec declares. It runs against a live HTTP endpoint, so it
treats the service under test as a black box.

## Running

Point `--service-url` at any running implementation of the contract:

```bash
cd contracts/conformance/notifications
uv venv && source .venv/bin/activate
uv pip install -e .
pytest \
  --service-url=https://notifications.your.example \
  --service-token=$YOUR_TOKEN
```

`--service-token` is only needed if the implementation enforces auth.
URL and token may also be supplied via `NEBULA_NOTIFICATIONS_URL` /
`NEBULA_NOTIFICATIONS_TOKEN`.

The bundled reference impl under `services/notifications/` has its own
test suite — see that directory's README for how to run it.

## What this checks

- Every documented status code is reachable with at least one request
  the contract considers valid.
- Response bodies match the schemas declared in the OpenAPI spec.
- Random invalid bodies don't produce 5xx (i.e., request validation
  happens before processing).

## What this does NOT check

- Side effects — the suite verifies the contract surface, not that a
  notification was actually delivered.
- Authorization semantics beyond "bearer token is honored or
  rejected".

For semantic checks beyond contract conformance, write integration
tests inside the implementation's own test suite (see
`services/notifications/tests/` for the OSS reference impl's tests).
