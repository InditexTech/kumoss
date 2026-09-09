# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Async wrappers around the az / gcloud / aws CLIs.

``CloudCli`` is the entry point; one ``CloudProvider`` subclass per cloud
handles credential readiness, login, per-scope engine env, and
scope-level resource listing for ``POST /v1/import/scope-resource-ids``.
"""

from ._base import CloudProvider
from ._cli import PROVIDERS, CloudCli

__all__ = ["PROVIDERS", "CloudCli", "CloudProvider"]
