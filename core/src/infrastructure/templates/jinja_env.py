# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Module-level Jinja2 environment used by every template adapter.

Lives next to the adapters that consume it (rather than in `shared/config`)
because it's a runtime object, not deployment-tunable configuration.
"""

from __future__ import annotations

from jinja2 import Environment, PackageLoader, select_autoescape

jinja_environment: Environment = Environment(  # nosemgrep: python.flask.security.xss.audit.direct-use-of-jinja2.direct-use-of-jinja2
    loader=PackageLoader(
        package_name="src.infrastructure",
        package_path="templates",
    ),
    autoescape=select_autoescape(
        default_for_string=True,
        default=False,
    ),
    auto_reload=False,
    trim_blocks=True,
    lstrip_blocks=True,
)
