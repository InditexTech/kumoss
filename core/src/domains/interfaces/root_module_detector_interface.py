# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from abc import ABC, abstractmethod


class IRootModuleDetector(ABC):
    """Detects Terraform root-module directories in a git repository."""

    @abstractmethod
    async def detect_roots(self, repo_uri: str) -> list[str]:
        """Return Terraform root-module directories, sorted lexicographically.

        Args:
            repo_uri: Git-cloneable repository URI.

        Returns:
            POSIX-style paths relative to the repo root.
        """
