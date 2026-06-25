# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from functools import cache
from src.domains.interfaces.git_provider_interface import IGitProvider
from src.infrastructure.filesystem.git.providers.github import GitHub
from src.shared.constants import GitProviderName


# lazyly initialize singleton (git-credentials are read at runtime)
@cache
def _github() -> GitHub:
    return GitHub()


class GitProviderFactory:
    def __init__(self, provider: GitProviderName):
        self.__provider = provider

    def get(self) -> IGitProvider:
        match self.__provider:
            case GitProviderName.GITHUB:
                return _github()
            case _:
                raise NotImplementedError()
