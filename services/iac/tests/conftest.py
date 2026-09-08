# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Test environment setup.

``src.main`` resolves ``Config.from_env()`` at import time, which only
reads secrets; the engine binary is the ``IAC_BINARY`` constant in
``src.config`` and is not read from the environment. Tests that reach
the engine build their own ``Config(iac_binary="sh")`` (see
``test_api._client_with``) so the per-request binary check passes in
engine-less environments; every subprocess call is patched.
"""
