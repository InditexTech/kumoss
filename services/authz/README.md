<!--
SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)

SPDX-License-Identifier: Apache-2.0
-->

# authz (reference implementation)

Reference implementation of [`contracts/openapi/authz.v1.yaml`](../../contracts/openapi/authz.v1.yaml).

The OSS default for the Nebula authorization contract:

- **`POST /v1/check`** — permissive by default (returns `authorized:
  true`). Production deploys should override this with real
  cloud-access logic. Set `NEBULA_AUTHZ_PERMISSIVE=false` to flip the
  default to `authorized: false` so misconfigurations are visible.
- **`GET /v1/users/me`** — looks up the user identified by the
  caller-supplied `X-User-Id` header, creating a record on first call.
  When the header is absent, returns an anonymous user with no roles.
- **Role storage** — JSON file at `NEBULA_AUTHZ_ROLE_STORE` (default
  `/data/roles.json`, a container-local path). Role assignments are lost
  when the container is recreated; point `NEBULA_AUTHZ_ROLE_STORE` at a
  mounted path if you need them to survive.
- **Default root admin** — when `NEBULA_AUTHZ_ROOT_ADMIN_EMAIL` is set,
  the user record with that email is granted the `admin` role on
  startup.
- **Admin endpoints** — `GET /v1/roles`, `GET /v1/users`,
  `POST /v1/users/{id}/roles`, `DELETE /v1/users/{id}/roles/{role}`.
  Caller must hold the `admin` role (asserted via X-User-Id header +
  verified against the store).
- **`GET /healthz`** — liveness probe.

This service's own `/v1/users/me`, `/v1/roles`, `/v1/users`, and role
admin endpoints are not consulted by Nebula at all — the core never
calls them. They exist only for callers of this service directly (or
for enterprises building on this reference impl) to manage this
service's own user/role store.

## What about OIDC?

OIDC token validation lives entirely in the **core**
(`core/src/infrastructure/auth/oidc.py`), not in this service. The core
calls this service in exactly one place: `POST /v1/auth/authorize` →
`POST /v1/check`, with a JSON body `{cloud, project, environment?,
user_id}` where `user_id` is `user.email or user.subject`. No
`X-User-Id` / `X-User-Email` headers are ever sent by the core on any
live path — those headers only matter if you call this service's other
endpoints directly. Nebula's own operation roles (`developer` <
`devops`) and panel roles (`viewer` < `editor` < `admin`) live in the
core database and are managed from the admin panel; this service's
role store affects only its own `/v1/users*` admin endpoints and has no
effect on what a user can do in Nebula.

The web app sends the repository URL as `project` and the IaC path as
`environment`; the contract caps `environment` at 32 characters, so a
long IaC path is rejected with `422` (surfaced by the core as `502`
when `/v1/check` is enabled).

## Configuration

| Env var                          | Required | Description                                           |
|----------------------------------|----------|-------------------------------------------------------|
| `NEBULA_AUTHZ_TOKEN`             | no       | Bearer token clients must present.                    |
| `NEBULA_AUTHZ_ROLE_STORE`        | no       | Path to the roles JSON file. Default `/data/roles.json`. Configures this service's own user/role store only — Nebula never reads it. |
| `NEBULA_AUTHZ_ROOT_ADMIN_EMAIL`  | no       | Email address granted the `admin` role on startup, in this service's own store. It is also used as that user's record key and `id`. |
| `NEBULA_AUTHZ_PERMISSIVE`        | no       | The only knob Nebula's own flow exercises. Default `true` — `/v1/check` returns true unconditionally. Set `false` for explicit-deny default. |

## Run locally

```bash
cd services/authz
uv sync
NEBULA_AUTHZ_ROOT_ADMIN_EMAIL=you@example.com \
  uv run fastapi run src/main.py --port 8083
```

```bash
curl -X POST http://localhost:8083/v1/check \
  -H 'Content-Type: application/json' \
  -d '{"cloud":"azure","project":"my-project"}'
```

The example above omits the `Authorization` header, so it only works
while `NEBULA_AUTHZ_TOKEN` is empty; once set, add
`-H 'Authorization: Bearer <token>'`.

## Tests

```bash
cd services/authz
uv sync --group tooling
uv run pytest
```

## Verifying conformance

The implementation-agnostic Schemathesis suite at
[`../../contracts/conformance/authz/`](../../contracts/conformance/authz/)
runs against any implementation of the authz contract.
