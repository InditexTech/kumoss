<!--
SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)

SPDX-License-Identifier: Apache-2.0
-->

# authz conformance suite

Implementation-agnostic check that any service claiming to satisfy
[`contracts/openapi/authz.v1.yaml`](../../openapi/authz.v1.yaml)
actually does.

## Running

Point `--service-url` at any running implementation of the contract:

```bash
cd contracts/conformance/authz
uv venv && source .venv/bin/activate
uv pip install -e .
pytest \
  --service-url=https://authz.your.example \
  --service-token=$YOUR_TOKEN
```

`--service-token` is only needed if the implementation enforces auth.
URL and token may also be supplied via `NEBULA_AUTHZ_URL` /
`NEBULA_AUTHZ_TOKEN`.

The bundled reference impl under `services/authz/` has its own test
suite — see that directory's README for how to run it.

## Notes

- The suite drives the API as a black box; it does NOT exercise OIDC
  semantics (the contract assumes the caller — typically the core —
  has already validated OIDC and forwards identity in headers).
- Admin endpoints are reachable only when the test caller has the
  `admin` role; without admin role assignments, those endpoints return
  the documented 403.
