# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Test-session bootstrap.

Importing ``src.main`` resolves ``Config`` from the environment and
validates ``config.yaml``'s ``llm`` section while doing so: the default
``llm.model`` (``anthropic/...``) demands ``ANTHROPIC_API_KEY``. Supply a
placeholder, and point ``KUMOSS_CONFIG`` at a path that does not exist so
a stray ``/etc/kumoss/config.yaml`` cannot leak into the run (the
defaults apply). Tests swap in their own config per case.
"""

import os

os.environ.setdefault("ANTHROPIC_API_KEY", "test-placeholder-not-a-real-key")
os.environ["KUMOSS_CONFIG"] = "/nonexistent/kumoss-llm-tests/config.yaml"
os.environ.pop("KUMOSS_LLM_TOKEN", None)
