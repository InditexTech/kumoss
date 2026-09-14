# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Runtime configuration for the IaC reference implementation."""

from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass

from .exceptions import ConfigError

_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


@dataclass(frozen=True)
class Config:
    """Resolved from environment at startup.

    - ``expected_token``: bearer token clients must present. If unset,
      the service accepts any (or no) token (intended for local
      development).
    - ``iac_binary``: name or absolute path of the IaC engine CLI to
      invoke, from ``IAC_BINARY``. The bundled image ships both
      engines, so this is ``tofu`` (OpenTofu, the default) or
      ``terraform``; any Terraform-compatible engine works. Lookup
      falls back to PATH so the bundled image needs no override.
      Asserted to be resolvable at startup so a misconfigured image
      fails fast instead of on the first request.
    - ``job_ttl``: seconds a terminal job record stays pollable at
      `GET /v1/jobs/{job_id}` before it is swept (then 404). Not
      environment-driven: it is a property of the service, changed here.
    - ``log_level``: Python logging level name `setup_logging` applies
      to the root logger. Not environment-driven either.
    """

    expected_token: str
    iac_binary: str
    job_ttl: int = 3600
    log_level: str = "INFO"

    def __post_init__(self) -> None:
        if not _engine_available(self.iac_binary):
            msg = (
                f"IaC engine binary {self.iac_binary!r} not found on PATH. "
                "Set IAC_BINARY to a binary on PATH or an absolute path."
            )
            raise ConfigError(msg)

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            expected_token=os.environ.get("NEBULA_IAC_TOKEN", ""),
            iac_binary=os.environ.get("IAC_BINARY", "tofu"),
        )


def setup_logging(config: Config) -> None:
    """Send every logger to stderr at ``config.log_level``.

    uvicorn only configures its own ``uvicorn*`` loggers, so without
    this the service's records fall back to ``logging.lastResort``:
    INFO dropped, warnings printed bare.
    """
    logging.basicConfig(level=config.log_level, format=_LOG_FORMAT)
    logging.getLogger().setLevel(config.log_level)


def _engine_available(binary: str) -> bool:
    return shutil.which(binary) is not None
