<!--
SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)

SPDX-License-Identifier: Apache-2.0
-->

# authz conformance suite

Implementation-agnostic check that any service claiming to satisfy
[`contracts/openapi/authz.v1.yaml`](../../openapi/authz.v1.yaml)
actually does. The contract defines two endpoints:

| Path | Method | Description |
|------|--------|-------------|
| `/access/v1/evaluation` | POST | AuthZEN 1.0 Access Evaluation |
| `/healthz` | GET | Liveness probe |

## Stub PDP

A minimal always-allow (or always-deny) stub is included for testing:

```bash
cd contracts/conformance/authz
uv sync
STUB_DECISION=true uv run uvicorn stub:app --port 8083
```

Set `STUB_TOKEN=mysecret` to require bearer auth on the stub.

## Running

Point `--service-url` at any running implementation of the contract:

```bash
cd contracts/conformance/authz
uv run pytest \
  --service-url=http://localhost:8083 \
  --service-token=$YOUR_TOKEN
```

`--service-token` is only needed if the implementation enforces auth.
URL and token may also be supplied via `KUMOSS_AUTHZ_URL` /
`KUMOSS_AUTHZ_TOKEN`.

Kumoss does not bundle an authz implementation; this suite is how you
check your own before pointing `services.authz.endpoint` at it.
