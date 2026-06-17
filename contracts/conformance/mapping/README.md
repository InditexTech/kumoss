<!--
SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)

SPDX-License-Identifier: Apache-2.0
-->

# mapping conformance suite

Implementation-agnostic check that any service claiming to satisfy
[`contracts/openapi/mapping.v1.yaml`](../../openapi/mapping.v1.yaml)
actually does.

The suite uses [Schemathesis](https://schemathesis.readthedocs.io/) to
generate requests from the OpenAPI spec and verify that responses match
what the spec declares. It runs against a live HTTP endpoint, so it
treats the service under test as a black box.

## Running against the OSS reference impl

```bash
docker compose up -d mapping
```

```bash
cd contracts/conformance/mapping
uv venv && source .venv/bin/activate
uv pip install -e .
pytest --service-url=http://localhost:8081
```

If the service is configured with `NEBULA_MAPPING_TOKEN`, pass it:

```bash
pytest --service-url=http://localhost:8081 --service-token=$NEBULA_MAPPING_TOKEN
```

## Running against your own implementation

```bash
pytest \
  --service-url=https://mapping.your.example \
  --service-token=$YOUR_TOKEN
```

## What this checks

- Every documented status code is reachable with at least one request
  the contract considers valid.
- Response bodies match the schemas declared in the OpenAPI spec.
- Random invalid bodies don't produce undocumented 5xx.

## What this does NOT check

- Side effects — the suite verifies the contract surface, not that the
  resolver returns something semantically meaningful for any specific
  identifier.
