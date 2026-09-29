# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Test-session bootstrap.

``src.shared.config.system_config`` builds the ``system_config`` singleton at
import time and validates the environment while doing so: the default
``llm.model`` (``anthropic/...``) demands ``ANTHROPIC_API_KEY`` and the
database section demands ``KUMOSS_SQL_DATABASE_URL``. Without them every test
module that transitively imports ``src`` fails at *collection*.

This file runs before any test module is imported, so it supplies placeholder
values for those two variables when they are absent. Real values already in
the environment always win (``setdefault``), so suites that need a live
PostgreSQL or Redis keep working when you point the URLs at your instances.
"""

import os

os.environ.setdefault("ANTHROPIC_API_KEY", "test-placeholder-not-a-real-key")
os.environ.setdefault(
    "KUMOSS_SQL_DATABASE_URL",
    "postgresql://kumoss:kumoss@localhost:5432/kumoss_test",
)
