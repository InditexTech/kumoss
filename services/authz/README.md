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
  `/data/roles.json`). The docker-compose stack mounts a named volume
  here so roles survive container restarts.
- **Default root admin** — when `NEBULA_AUTHZ_ROOT_ADMIN_EMAIL` is set,
  the user record with that email is granted the `admin` role on
  startup.
- **Admin endpoints** — `GET /v1/users`, `POST /v1/users/{id}/roles`,
  `DELETE /v1/users/{id}/roles/{role}`. Caller must hold the `admin`
  role (asserted via X-User-Id header + verified against the store).

## What about OIDC?

OIDC token validation lives in the **core**, not in this service. The
core validates upstream OIDC tokens (e.g., from Keycloak / Auth0 / your
IdP) and forwards the resolved identity as `X-User-Id` /
`X-User-Email` headers when calling this service. That keeps the
contract simple and the service implementation independent of any
particular OIDC provider.

## Configuration

| Env var                          | Required | Description                                           |
|----------------------------------|----------|-------------------------------------------------------|
| `NEBULA_AUTHZ_TOKEN`             | no       | Bearer token clients must present.                    |
| `NEBULA_AUTHZ_ROLE_STORE`        | no       | Path to the roles JSON file. Default `/data/roles.json`. |
| `NEBULA_AUTHZ_ROOT_ADMIN_EMAIL`  | no       | User ID to grant `admin` role on startup.             |
| `NEBULA_AUTHZ_PERMISSIVE`        | no       | Default `true` — `/v1/check` returns true unconditionally. Set `false` for explicit-deny default. |

## Run locally

```bash
cd services/authz
uv venv && source .venv/bin/activate
uv pip install -e '.[dev]'
NEBULA_AUTHZ_ROOT_ADMIN_EMAIL=you@example.com \
  uvicorn src.main:app --host 0.0.0.0 --port 8083
```

```bash
curl -X POST http://localhost:8083/v1/check \
  -H 'Content-Type: application/json' \
  -d '{"cloud":"azure","project":"my-project"}'
```

## Tests

```bash
cd services/authz
uv pip install -e '.[dev]'
pytest
```

## Verifying conformance

The implementation-agnostic Schemathesis suite at
[`../../contracts/conformance/authz/`](../../contracts/conformance/authz/)
runs against any implementation of the authz contract.
