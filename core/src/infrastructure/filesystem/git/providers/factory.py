# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from src.domains.interfaces.git_provider_interface import IGitProvider
from src.infrastructure.filesystem.git.providers.github import GitHub
from src.shared.constants import GitProviderName


class GitProviderFactory:
    def __init__(self, provider: GitProviderName):
        self.__provider = provider

    def get(self) -> IGitProvider:
        match self.__provider.name:
            case "GITHUB":
                return _git
            case _:
                raise NotImplementedError()


# singleton
_git = GitHub()
