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
uv venv && source .venv/bin/activate
uv pip install -e .
pytest \
  --service-url=https://iac.your.example \
  --service-token=$YOUR_TOKEN
```

`--service-token` is only needed if the implementation enforces auth.
URL and token may also be supplied via `NEBULA_IAC_URL` /
`NEBULA_IAC_TOKEN`.

The bundled reference impl under `services/iac/` has its own test
suite — see that directory's README for how to run it.

## What this checks

- Every documented status code is reachable with at least one request
  the contract considers valid.
- Response bodies match the schemas declared in the OpenAPI spec.
- Random invalid bodies don't produce undocumented 5xx.

## What this does NOT check

- That `terraform plan` actually produces accurate output for your
  modules.
- Cloud-provider authentication semantics.
- Performance or concurrent-request behavior.
