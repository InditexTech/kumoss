# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0


def derive_project_name(repo_uri: str) -> str:
    """Project name = last `/` or `:` segment of the URI, with .git stripped.

    Used as a fallback for tracer/authz `project` when the mapping
    passthrough is not consulted (or returns the identifier unchanged
    under the identity-default). Stable, readable, deterministic.
    """
    s = repo_uri.rstrip("/")
    sep = max(s.rfind("/"), s.rfind(":"))
    tail = s[sep + 1 :] if sep >= 0 else s
    return tail[:-4] if tail.endswith(".git") else tail
