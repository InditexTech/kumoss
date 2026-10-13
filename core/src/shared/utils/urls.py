# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from urllib.parse import urlparse


def is_https_url(uri: str) -> bool:
    try:
        parsed = urlparse(uri.strip())
        return parsed.scheme.lower() == "https" and bool(parsed.hostname)
    except ValueError:
        return False
