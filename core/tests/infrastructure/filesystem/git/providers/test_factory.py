# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import unittest
from unittest.mock import patch

from src.infrastructure.filesystem.git.providers.factory import GitProviderFactory
from src.infrastructure.filesystem.git.providers.github import GitHub
from src.shared.constants import GitProviderName


class TestGitProviderFactory(unittest.TestCase):
    def test_returns_github_for_github_enum(self):
        # GitHub() reads system_config.git for HTTP basic auth at construction
        # time; patch the module-level config so the test doesn't depend on
        # the real environment.
        with patch(
            "src.infrastructure.filesystem.git.providers.github.system_config"
        ) as cfg:
            cfg.git.pat_user = "u"
            cfg.git.pat_token = "t"
            provider = GitProviderFactory(GitProviderName.GITHUB).get()
        self.assertIsInstance(provider, GitHub)

    def test_raises_not_implemented_for_unsupported_provider(self):
        with self.assertRaises(NotImplementedError):
            GitProviderFactory(GitProviderName.AZURE_DEVOPS).get()


if __name__ == "__main__":
    unittest.main()
