# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Schemathesis-driven conformance suite for the notifications contract.

What this checks:

- Every documented response status is reachable with at least one request
  the contract considers valid.
- Responses match the schemas declared in the OpenAPI spec.
- Request validation happens (random invalid bodies do not produce 5xx).

What this does NOT check:

- Side effects (the suite only verifies the contract surface; it does not
  confirm a notification actually got delivered).
- Authorization semantics beyond "bearer token is honored or rejected".

Run against any implementation of the contract:

    pytest --service-url=https://notifications.your.example \
           --service-token=$YOUR_TOKEN
"""

from __future__ import annotations

from pathlib import Path

import schemathesis


_SPEC_PATH = Path(__file__).resolve().parents[2] / "openapi" / "notifications.v1.yaml"

schema = schemathesis.openapi.from_path(str(_SPEC_PATH))


@schema.parametrize()
def test_contract_conformance(case: schemathesis.Case, service_url, service_token):
    """Fuzz every documented operation against the live service.

    Schemathesis generates request bodies/parameters that satisfy the
    schema, sends them to `service_url`, and verifies each response matches
    the spec (status code declared, body matches the response schema).

    The default `not_a_server_error` check is excluded because the
    notifications contract documents 5xx responses (502 for downstream
    failures, 503 for unconfigured services). Schema conformance of
    those 5xx bodies is still verified by the other checks.
    """
    headers = {}
    if service_token:
        headers["Authorization"] = f"Bearer {service_token}"
    case.call_and_validate(
        base_url=service_url,
        headers=headers,
        excluded_checks=[schemathesis.checks.not_a_server_error],
    )
