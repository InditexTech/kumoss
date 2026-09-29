<!--
SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)

SPDX-License-Identifier: Apache-2.0
-->

# mapping (reference implementation)

Reference implementation of [`contracts/openapi/mapping.v1.yaml`](../../contracts/openapi/mapping.v1.yaml).

The OSS default for the Kumoss mapping contract: identity passthrough.
Whatever `identifier` the caller sends is returned as both the
`repo_url` and the `identifier`. Useful for users who pass real git
URLs directly and don't have (or need) a business-product → IaC
catalogue.

Enterprise implementations of this contract resolve identifiers against
an internal source of truth (CMDB, Backstage, a spreadsheet, …) and
return the canonical IaC repo for each.

`terraform_provider` and `scope_id` are best effort. `null` means "I do
not know, ask the user" — never "there is none". The caller skips the
wizard step for every field it gets a value for, so answering with a
guess removes the user's chance to correct it. This implementation
knows nothing beyond what it was sent: it echoes `terraform_provider`
back when the caller supplies one and always returns a null `scope_id`.

The service is internal-only: the core api forwards browser requests
to it via `POST /v1/mapping/resolve`. It is not reachable from the
browser directly.

## What it does

- `POST /v1/resolve` — returns `{repo_url: identifier, identifier: identifier,
  terraform_provider: <whatever was sent, or null>, scope_id: null}`.
  Nothing is truncated.
- `GET /healthz` — liveness probe.
- Bearer-token auth on `/v1/resolve` if `KUMOSS_MAPPING_TOKEN` is set.
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
| `KUMOSS_MAPPING_TOKEN`         | no       | Bearer token clients must present.   |

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

```json
{
  "repo_url": "https://github.com/me/my-iac.git",
  "identifier": "https://github.com/me/my-iac.git",
  "terraform_provider": null,
  "scope_id": null
}
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
