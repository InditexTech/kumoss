# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from functools import cache
from src.domains.interfaces.git_provider_interface import IGitProvider
from src.infrastructure.filesystem.git.providers._github import GitHub
from src.infrastructure.filesystem.git.providers._azure_devops import AzureDevOps
from src.infrastructure.filesystem.git.providers._gitlab import GitLab
from src.shared.constants import GitProviderName


# lazily initialize singleton (git-credentials are read at runtime)
@cache
def _github() -> GitHub:
    return GitHub()


@cache
def _azure_devops() -> AzureDevOps:
    return AzureDevOps()


@cache
def _gitlab() -> GitLab:
    return GitLab()


class GitProviderFactory:
    def __init__(self, provider: GitProviderName):
        self.__provider = provider

    def get(self) -> IGitProvider:
        match self.__provider:
            case GitProviderName.GITHUB:
                return _github()
            case GitProviderName.AZURE_DEVOPS:
                return _azure_devops()
            case GitProviderName.GITLAB:
                return _gitlab()
            case _:
                raise NotImplementedError()
