# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Importing ``src.main`` resolves ``Config`` from the environment, which
asserts a webhook URL. Provide one so the app module can be imported;
tests swap in their own ``Config`` per case."""

import os

os.environ.setdefault("SLACK_WEBHOOK_URL", "https://hooks.slack.example/T0/B0/conftest")
