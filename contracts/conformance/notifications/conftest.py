"""Pytest configuration for the notifications conformance suite.

The suite is implementation-agnostic: pass `--service-url=<base-url>` (or
set NEBULA_NOTIFICATIONS_URL) and the tests fuzz that URL against the
contract. A bearer token can be supplied via `--service-token` /
NEBULA_NOTIFICATIONS_TOKEN — required when the implementation is
configured to enforce auth.
"""

from __future__ import annotations

import os

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--service-url",
        default=os.environ.get("NEBULA_NOTIFICATIONS_URL", "http://localhost:8080"),
        help="Base URL of the notifications service to test (default: http://localhost:8080).",
    )
    parser.addoption(
        "--service-token",
        default=os.environ.get("NEBULA_NOTIFICATIONS_TOKEN", ""),
        help="Bearer token to include on requests, if the service requires auth.",
    )


@pytest.fixture(scope="session")
def service_url(pytestconfig: pytest.Config) -> str:
    return pytestconfig.getoption("--service-url")


@pytest.fixture(scope="session")
def service_token(pytestconfig: pytest.Config) -> str:
    return pytestconfig.getoption("--service-token")
