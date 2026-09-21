<!--
SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)

SPDX-License-Identifier: Apache-2.0
-->

# Conformance suites

Per-service Schemathesis test packs. Any implementation that wants to
claim it satisfies a Nebula contract must pass the matching suite.

Layout: `<service>/` — one directory per service, mirroring
`../openapi/`. Each contains the Schemathesis configuration, fixtures,
and any custom checks that aren't expressible directly in OpenAPI.

Both the in-tree reference implementations under `../../services/` and
external implementations (e.g., enterprise variants in private repos)
should be runnable against these suites unchanged.
