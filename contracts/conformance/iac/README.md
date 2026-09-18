<!--
SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)

SPDX-License-Identifier: Apache-2.0
-->

# IaC conformance suite

Implementation-agnostic check that any service claiming to satisfy
[`contracts/openapi/iac.v1.yaml`](../../openapi/iac.v1.yaml)
actually does.

The suite uses [Schemathesis](https://schemathesis.readthedocs.io/) to
generate requests from the OpenAPI spec and verify that responses match
what the spec declares.

## Running

Point `--service-url` at any running implementation of the contract:

```bash
cd contracts/conformance/iac
uv sync
uv run pytest \
  --service-url=https://iac.your.example \
  --service-token=$YOUR_TOKEN
```

`--service-token` is only needed if the implementation enforces auth.
URL and token may also be supplied via `NEBULA_IAC_URL` /
`NEBULA_IAC_TOKEN`.

The bundled reference impl under `services/iac/` has its own test
suite — see that directory's README for how to run it.

## What this checks

- Every response the implementation returns conforms to the schema
  declared for its status code.
- Response bodies match the schemas declared in the OpenAPI spec,
  including for randomly generated invalid request bodies.

## What this does NOT check

- That 5xx responses are absent. The default `not_a_server_error` check
  is excluded, because the contract documents 5xx statuses; their
  bodies are still validated like any other response.
- That the engine commands the jobs run actually produce accurate
  output for your modules.
- Cloud-provider authentication semantics.
- Performance or concurrent-request behavior.

## Known deviation of the bundled reference

The bundled reference implementation answers `501 Not Implemented` on
the `/v1/import`, `/v1/import/state-resource-ids` and
`/v1/import/scope-resource-ids` operations. The contract does not list
`501` for them, so those three operations are **expected to fail this
suite** when it is run against the bundled image.
