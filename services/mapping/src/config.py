# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Runtime configuration for the mapping reference implementation."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Config:
    """Resolved from environment at startup.

    - ``expected_token``: bearer token clients must present. If unset, the
      service accepts any (or no) token. Local-dev fallback.
    - ``cors_origins``: origins allowed to call the service from the
      browser. Mapping is the only Nebula service called from the React
      frontend directly, so CORS matters here. The default permits the
      bundled docker-compose stack; override via NEBULA_MAPPING_CORS_ORIGINS
      (comma-separated).
    """

    expected_token: str
    cors_origins: list[str] = field(default_factory=list)

    @classmethod
    def from_env(cls) -> "Config":
        origins_csv = os.environ.get(
            "NEBULA_MAPPING_CORS_ORIGINS",
            "http://localhost,http://localhost:5173,http://localhost:80",
        )
        return cls(
            expected_token=os.environ.get("NEBULA_MAPPING_TOKEN", ""),
            cors_origins=[o.strip() for o in origins_csv.split(",") if o.strip()],
        )
