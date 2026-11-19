# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from abc import ABC, abstractmethod
from pathlib import Path

from src.domains.value_objects.manifest import Manifest


class IManifestRepository(ABC):
    """Persists the manifest that lives inside a root module's directory."""

    @abstractmethod
    def load(self, directory: Path) -> Manifest | None:
        """The manifest of the root module at ``directory``, None when there is none.

        Raises:
            ManifestReadError: When a manifest exists but cannot be read.
        """

    @abstractmethod
    def save(self, directory: Path, manifest: Manifest) -> None:
        """Write ``manifest`` into the root module at ``directory``, replacing any."""
