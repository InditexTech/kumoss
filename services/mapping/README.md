<!--
SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)

SPDX-License-Identifier: Apache-2.0
-->

# mapping (reference implementation)

Reference implementation of [`contracts/openapi/mapping.v1.yaml`](../../contracts/openapi/mapping.v1.yaml)
(contract 2.0.0).

The OSS default for the Kumoss mapping contract: it lets users type a
repository *name* instead of a full clone URL. The core calls it when
the web wizard scans a repository, so `foo` becomes
`https://github.com/MySuperOrg/foo.git`. Organizations with a real
catalogue (CMDB, Backstage…) replace it with their own implementation
of the same contract.

## What it does

- `POST /v1/resolve` resolves `identifier` to a `repo_url`:
  - An `https://` URL passes through unchanged (scheme case-insensitive).
  - A bare repository name (letters, digits, `.`, `_`, `-`, no slashes)
    becomes `MAPPING_PREFIX_IDENTIFIER` + name + `.git`. A name already
    ending in `.git` does not get a second one.
  - Anything else (`team/foo`, SSH or `http://` URLs, `..`), or a bare
    name while no prefix is configured, answers `404` with a problem
    document saying why.
  - `identifier` is echoed verbatim.
- `GET /healthz` — liveness probe.
- Bearer-token auth on `/v1/resolve` if `KUMOSS_MAPPING_TOKEN` is set.
  Leave it blank in a shared network only for local experimentation —
  a blank token disables the check entirely, so set one whenever this
  service is reachable by anyone other than the core. Tokens are
  compared in constant time (`hmac.compare_digest`).

Status codes this reference emits: `200`, `400` (malformed JSON), `401`
(bad or missing token), `404` (not resolvable), `422` (body fails the
schema, including the pre-2.0 `terraform_provider`) and `500`. It never
emits `403` or `502`: it has no access rules and no downstream catalogue.

The `.git` suffix is always added, so the prefix scheme suits hosts
whose clone URLs end in `.git` (GitHub, GitLab, Bitbucket, Gitea).
Azure DevOps clone URLs have no `.git`; users of it type the full URL,
which passes through.

## Configuration

| Env var                     | Required | Description |
|-----------------------------|----------|-------------|
| `MAPPING_PREFIX_IDENTIFIER` | no       | Base URL a bare repository name is appended to, e.g. `https://github.com/MySuperOrg/`. A trailing `/` is added if missing. Empty: only full `https://` URLs resolve. |
| `KUMOSS_MAPPING_TOKEN`      | no       | Bearer token clients must present. |
| `LOG_LEVEL`                 | no       | Root log level (default `INFO`). |

Configuration is checked at startup: a prefix that is not an `https://`
URL with a host, or that embeds a password, a query or a fragment, or
an unknown log level, raises `ConfigError` and the process exits.

## Troubleshooting

- Container exits at boot with `ConfigError`: fix
  `MAPPING_PREFIX_IDENTIFIER` (or `LOG_LEVEL`) in `services/mapping/.env`.
- The wizard says a name cannot be resolved and mentions
  `MAPPING_PREFIX_IDENTIFIER`: set it, or type the full `https://` URL.
- `401` at the core: `KUMOSS_MAPPING_TOKEN` differs between `core/.env`
  and `services/mapping/.env`.

## Run locally

```bash
cd services/mapping
uv sync
MAPPING_PREFIX_IDENTIFIER=https://github.com/MySuperOrg/ \
  uv run fastapi run src/main.py --port 8081
```

```bash
curl -X POST http://localhost:8081/v1/resolve \
  -H 'Content-Type: application/json' \
  -d '{"identifier":"foo"}'
```

```json
{
  "repo_url": "https://github.com/MySuperOrg/foo.git",
  "identifier": "foo"
}
```

## Run in docker compose

The service is wired into the repo-root `docker-compose.yml`, which
loads `services/mapping/.env` (copy `env.sample` to `.env` in this
directory). Set `MAPPING_PREFIX_IDENTIFIER` and `KUMOSS_MAPPING_TOKEN`
there; `services.mapping` is enabled in the root `config.yaml` by
default.

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
