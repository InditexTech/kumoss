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

The service is internal-only: the core api forwards browser requests
to it via `POST /v1/mapping/resolve`. It is not reachable from the
browser directly.

## What it does

- `POST /v1/resolve` — returns `{repo_url: identifier, project:
  identifier[:128]}` (the `project` is truncated to 128 characters;
  `repo_url` is not).
- `GET /healthz` — liveness probe.
- Bearer-token auth on `/v1/resolve` if `NEBULA_MAPPING_TOKEN` is set.
  Leave it blank in a shared network only for local experimentation —
  a blank token disables the check entirely, so set one whenever this
  service is reachable by anyone other than the core.

The contract documents `400`/`403`/`404`/`502` for real catalogue
backends (bad identifier, no access, unknown identifier, catalogue
unreachable). This identity-passthrough reference never produces any
of them — it only ever emits `200`, `401` (bad/missing token), `422`
(malformed request body), or `500`.

## Configuration

| Env var                        | Required | Description                          |
|--------------------------------|----------|--------------------------------------|
| `NEBULA_MAPPING_TOKEN`         | no       | Bearer token clients must present.   |

## Run locally

```bash
cd services/mapping
uv sync
uv run fastapi run src/main.py --port 8081
```

```bash
curl -X POST http://localhost:8081/v1/resolve \
  -H 'Content-Type: application/json' \
  -d '{"identifier":"https://github.com/me/my-iac.git"}'
```

## Tests

```bash
cd services/mapping
uv sync --group tooling
uv run pytest
```

## Verifying conformance

The implementation-agnostic Schemathesis suite at
[`../../contracts/conformance/mapping/`](../../contracts/conformance/mapping/)
runs against any implementation of the mapping contract.
