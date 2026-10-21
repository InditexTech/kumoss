# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from src.domains.value_objects.token_claims import TokenClaims


def test_token_claims_carries_groups():
    tc = TokenClaims(
        issuer="https://issuer.example.com/",
        subject="sub-123",
        email="a@b.com",
        name="A",
        email_verified=True,
        groups=["team-a", "team-b"],
    )
    assert tc.groups == ["team-a", "team-b"]


def test_token_claims_groups_default_empty():
    tc = TokenClaims(
        issuer="urn:kumoss:dev",
        subject="dev",
        email=None,
        name=None,
    )
    assert tc.groups == []
