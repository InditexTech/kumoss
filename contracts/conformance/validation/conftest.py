"""Pytest configuration for the validation conformance suite.

Implementation-agnostic: pass `--service-url=<base-url>` (or set
NEBULA_VALIDATION_URL) and the tests fuzz that URL against the contract.
A bearer token can be supplied via `--service-token` /
NEBULA_VALIDATION_TOKEN if the implementation enforces auth.
"""

from __future__ import annotations

import os

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--service-url",
        default=os.environ.get("NEBULA_VALIDATION_URL", "http://localhost:8082"),
        help="Base URL of the validation service to test (default: http://localhost:8082).",
    )
    parser.addoption(
        "--service-token",
        default=os.environ.get("NEBULA_VALIDATION_TOKEN", ""),
        help="Bearer token to include on requests, if the service requires auth.",
    )


@pytest.fixture(scope="session")
def service_url(pytestconfig: pytest.Config) -> str:
    return pytestconfig.getoption("--service-url")


@pytest.fixture(scope="session")
def service_token(pytestconfig: pytest.Config) -> str:
    return pytestconfig.getoption("--service-token")
