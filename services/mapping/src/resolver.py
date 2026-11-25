# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Turn an identifier into a clone URL: passthrough or prefix + name."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

# One repository name: no slashes, so an identifier can never climb out
# of the configured prefix or address a nested path.
_REPO_NAME = re.compile(r"[A-Za-z0-9._-]+")
_GIT_SUFFIX = ".git"


class NotResolvable(LookupError):
    """The identifier maps to no repository; the message says why."""


def is_https_url(value: str) -> bool:
    try:
        parts = urlsplit(value)
        return parts.scheme.lower() == "https" and bool(parts.hostname)
    except ValueError:
        return False


def resolve(identifier: str, prefix: str) -> str:
    """The ``repo_url`` for ``identifier``.

    An ``https://`` URL passes through unchanged apart from surrounding
    whitespace, which is stripped so the answer meets the contract's
    ``repo_url`` pattern.
    A bare repository name becomes ``prefix + name + ".git"`` (no second
    ``.git`` when the name already ends in one). Anything else, or a bare
    name with no prefix configured, raises ``NotResolvable``.
    """
    name = identifier.strip()
    if is_https_url(name):
        return name
    stem = name.removesuffix(_GIT_SUFFIX)
    if not _REPO_NAME.fullmatch(name) or stem in {"", ".", ".."}:
        raise NotResolvable(
            "Identifier is neither an https:// repository URL nor a repository "
            "name (letters, digits, '.', '_' and '-')."
        )
    if not prefix:
        raise NotResolvable(
            "Identifier is a repository name but MAPPING_PREFIX_IDENTIFIER is "
            "not set; pass a full https:// URL or configure the prefix."
        )
    return f"{prefix}{stem}{_GIT_SUFFIX}"
