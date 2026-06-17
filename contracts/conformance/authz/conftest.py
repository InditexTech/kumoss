# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Pytest configuration for the authz conformance suite."""

from __future__ import annotations

import os

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--service-url",
        default=os.environ.get("NEBULA_AUTHZ_URL"),
        help="Base URL of the authz service to test (or set NEBULA_AUTHZ_URL).",
    )
    parser.addoption(
        "--service-token",
        default=os.environ.get("NEBULA_AUTHZ_TOKEN", ""),
        help="Bearer token to include on requests, if the service requires auth.",
    )


@pytest.fixture(scope="session")
def service_url(pytestconfig: pytest.Config) -> str:
    url = pytestconfig.getoption("--service-url")
    if not url:
        raise pytest.UsageError(
            "--service-url is required (or set NEBULA_AUTHZ_URL). "
            "Point it at the implementation you want to verify."
        )
    return url


@pytest.fixture(scope="session")
def service_token(pytestconfig: pytest.Config) -> str:
    return pytestconfig.getoption("--service-token")
