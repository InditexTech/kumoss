<!--
SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)

SPDX-License-Identifier: Apache-2.0
-->

# mapping (reference implementation)

Reference implementation of [`contracts/openapi/mapping.v1.yaml`](../../contracts/openapi/mapping.v1.yaml).

The OSS default for the Nebula mapping contract: identity passthrough.
Whatever `identifier` the caller sends is returned as both the
`repo_url` and the canonical `project` name. Useful for users who pass
real git URLs directly and don't have (or need) a business-product →
IaC catalogue.

Enterprise implementations of this contract resolve identifiers against
an internal source of truth (CMDB, Backstage, a spreadsheet, …) and
return the canonical IaC repo for each.

## What it does

- `POST /v1/resolve` — returns `{repo_url: identifier, project: identifier}`.
- `GET /healthz` — liveness probe.
- Bearer-token auth on `/v1/resolve` if `NEBULA_MAPPING_TOKEN` is set.
- CORS — mapping is the only Nebula service the browser calls
  directly, so origins are configurable via `NEBULA_MAPPING_CORS_ORIGINS`
  (comma-separated). Defaults cover the docker-compose stack.

## Configuration

| Env var                        | Required | Description                          |
|--------------------------------|----------|--------------------------------------|
| `NEBULA_MAPPING_TOKEN`         | no       | Bearer token clients must present.   |
| `NEBULA_MAPPING_CORS_ORIGINS`  | no       | Comma-separated list of allowed CORS origins. Defaults to `http://localhost,http://localhost:5173,http://localhost:80`. |

## Run locally

```bash
cd services/mapping
uv venv && source .venv/bin/activate
uv pip install -e '.[dev]'
uvicorn src.main:app --host 0.0.0.0 --port 8081
```

```bash
curl -X POST http://localhost:8081/v1/resolve \
  -H 'Content-Type: application/json' \
  -d '{"identifier":"https://github.com/me/my-iac.git"}'
```

## Tests

```bash
cd services/mapping
uv pip install -e '.[dev]'
pytest
```

## Verifying conformance

The implementation-agnostic Schemathesis suite at
[`../../contracts/conformance/mapping/`](../../contracts/conformance/mapping/)
runs against any implementation of the mapping contract.
