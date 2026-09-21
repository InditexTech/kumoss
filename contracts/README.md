<!--
SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)

SPDX-License-Identifier: Apache-2.0
-->

# Contracts

The canonical OSS specification for Nebula's microservice interfaces.

This directory is the source of truth for what every Nebula service —
including third-party and enterprise implementations — must satisfy. The
core engine consumes these contracts via a generated HTTP client; it
never imports a service implementation directly.

## Layout

- `openapi/<service>.v<major>.yaml` — hand-written OpenAPI 3.1 specs.
  One file per service, versioned in the URL path (`/v1/...`). Breaking
  changes require a new major and a new file.
- `conformance/<service>/` — Schemathesis-driven test packs that any
  implementation (the in-tree reference impl in `services/` or a
  third-party implementation) must pass to claim contract conformance.

## Conventions

- Errors: RFC 7807 (`application/problem+json`) across every endpoint.
- Auth: `Authorization: Bearer <token>`; the token type is documented
  per endpoint in the spec.
- Versioning: semver on the contract. Two majors may run in parallel
  during a deprecation window.
- CI checks (forthcoming): `spectral lint` on every PR that touches
  `openapi/`; `oasdiff` to detect unintentional breaking changes.
