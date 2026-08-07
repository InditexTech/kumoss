# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Test environment setup.

``src.main`` resolves ``Config.from_env()`` at import time, and
``Config.__post_init__`` fails fast when the terraform binary cannot be
resolved. Point it at ``sh`` (always present) so the suite collects in
terraform-less environments (e.g. the CI/test container); tests never
invoke the real binary — every subprocess call is patched.
"""

import os

os.environ.setdefault("TERRAFORM_BINARY", "sh")
