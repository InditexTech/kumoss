<!--
SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)

SPDX-License-Identifier: Apache-2.0
-->

# authz conformance suite

Implementation-agnostic check that any service claiming to satisfy
[`contracts/openapi/authz.v1.yaml`](../../openapi/authz.v1.yaml)
actually does.

## Running against the OSS reference impl

```bash
docker compose up -d authz
```

```bash
cd contracts/conformance/authz
uv venv && source .venv/bin/activate
uv pip install -e .
pytest --service-url=http://localhost:8083 --service-token=$NEBULA_AUTHZ_TOKEN
```

## Running against your own implementation

```bash
pytest \
  --service-url=https://authz.your.example \
  --service-token=$YOUR_TOKEN
```

## Notes

- The suite drives the API as a black box; it does NOT exercise OIDC
  semantics (the contract assumes the caller — typically the core —
  has already validated OIDC and forwards identity in headers).
- Admin endpoints are reachable only when the test caller has the
  `admin` role; without admin role assignments, those endpoints return
  the documented 403.
