# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Test environment setup.

``src.main`` resolves ``Config.from_env()`` at import time, and
``Config.__post_init__`` fails fast when the IaC engine binary cannot
be resolved. Point it at ``sh`` (always present) so the suite collects
in engine-less environments (e.g. the CI/test container); unit tests
never invoke the real binary — every subprocess call is patched. The
real-engine checks live in ``test_integration_engine.py`` and skip
themselves when no engine is installed.
"""

import os

os.environ.setdefault("IAC_BINARY", "sh")
