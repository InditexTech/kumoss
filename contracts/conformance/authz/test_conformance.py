# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Schemathesis-driven conformance suite for the authz contract."""

from __future__ import annotations

from pathlib import Path

import schemathesis


_SPEC_PATH = Path(__file__).resolve().parents[2] / "openapi" / "authz.v1.yaml"

schema = schemathesis.openapi.from_path(str(_SPEC_PATH))


@schema.parametrize()
def test_contract_conformance(case: schemathesis.Case, service_url, service_token):
    """Fuzz every documented operation against the live service.

    Excludes `not_a_server_error` because the contract documents 502 for
    downstream identity-backend failures; schema conformance of any 5xx
    bodies is still verified by the other checks.
    """
    headers = {}
    if service_token:
        headers["Authorization"] = f"Bearer {service_token}"
    case.call_and_validate(
        base_url=service_url,
        headers=headers,
        excluded_checks=[schemathesis.checks.not_a_server_error],
    )
