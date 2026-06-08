# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Schemathesis-driven conformance suite for the mapping contract.

What this checks:

- Every documented response status is reachable with at least one
  request the contract considers valid.
- Responses match the schemas declared in the OpenAPI spec.
- Random invalid bodies do not produce undocumented 5xx.

What this does NOT check:

- Side effects (the suite verifies the contract surface, not that the
  resolver returns something semantically meaningful for any specific
  identifier).
- CORS behavior — that is best validated from a real browser context.

Run against the OSS reference impl spun up by docker-compose:

    pytest --service-url=http://localhost:8081

Or against your own implementation:

    pytest --service-url=https://mapping.your.example \
           --service-token=$YOUR_TOKEN
"""

from __future__ import annotations

from pathlib import Path

import schemathesis


_SPEC_PATH = Path(__file__).resolve().parents[2] / "openapi" / "mapping.v1.yaml"

schema = schemathesis.openapi.from_path(str(_SPEC_PATH))


@schema.parametrize()
def test_contract_conformance(case: schemathesis.Case, service_url, service_token):
    """Fuzz every documented operation against the live service.

    The default `not_a_server_error` check is excluded because the
    contract documents 502 responses for downstream catalogue failures.
    Schema conformance of those 5xx bodies is still verified by the
    other checks.
    """
    headers = {}
    if service_token:
        headers["Authorization"] = f"Bearer {service_token}"
    case.call_and_validate(
        base_url=service_url,
        headers=headers,
        excluded_checks=[schemathesis.checks.not_a_server_error],
    )
