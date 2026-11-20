# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Runtime configuration for the mapping reference implementation."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from urllib.parse import urlsplit


class ConfigError(ValueError):
    """Raised when the resolved service configuration is unusable."""


def normalize_prefix(raw: str) -> str:
    """Validate ``MAPPING_PREFIX_IDENTIFIER`` and give it a trailing slash.

    Empty stays empty (bare names then cannot be resolved). Anything else
    must be an ``https://`` URL with a host and no password, query or
    fragment: it is the start of every clone URL this service answers.
    """
    prefix = raw.strip()
    if not prefix:
        return ""
    try:
        parts = urlsplit(prefix)
        password = parts.password
    except ValueError as exc:
        raise ConfigError(f"MAPPING_PREFIX_IDENTIFIER is not a URL: {exc}") from exc
    if parts.scheme.lower() != "https" or not parts.hostname:
        raise ConfigError(
            "MAPPING_PREFIX_IDENTIFIER must be an https:// URL with a host, "
            "e.g. https://github.com/my-org/."
        )
    if password is not None:
        raise ConfigError(
            "MAPPING_PREFIX_IDENTIFIER must not embed a password or token."
        )
    # A bare trailing `?` or `#` parses as an empty query or fragment, yet
    # would still swallow the appended repository name.
    if "?" in prefix or "#" in prefix:
        raise ConfigError(
            "MAPPING_PREFIX_IDENTIFIER must not carry a query or fragment."
        )
    return prefix if prefix.endswith("/") else prefix + "/"


@dataclass(frozen=True)
class Config:
    """Resolved from environment at startup.

    - ``expected_token``: bearer token clients must present. If unset, the
      service accepts any (or no) token (intended for local development).
    - ``prefix_identifier``: base URL a bare repository name is appended
      to (``MAPPING_PREFIX_IDENTIFIER``), normalized to end in ``/``.
      Empty means only full ``https://`` URLs resolve.
    - ``log_level``: Python logging level name applied to the root logger
      (``LOG_LEVEL``, default ``INFO``).
    """

    expected_token: str
    prefix_identifier: str = ""
    log_level: str = "INFO"

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "prefix_identifier", normalize_prefix(self.prefix_identifier)
        )
        level = logging.getLevelNamesMapping().get(self.log_level)
        if level is None:
            raise ConfigError(f"LOG_LEVEL {self.log_level!r} is not a logging level.")
        logging.basicConfig(level=level)
        logging.getLogger().setLevel(level)

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            expected_token=os.environ.get("KUMOSS_MAPPING_TOKEN", ""),
            prefix_identifier=os.environ.get("MAPPING_PREFIX_IDENTIFIER", ""),
            log_level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        )
