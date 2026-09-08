# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Test environment setup.

``src.main`` resolves ``Config.from_env()`` at import time. Point
``IAC_BINARY`` at ``sh`` (always present) so the default config
works in engine-less environments (e.g. the CI/test container);
tests never invoke the real binary — every subprocess call is patched.
"""

import os

os.environ.setdefault("IAC_BINARY", "sh")
