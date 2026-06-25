# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.infrastructure.filesystem import configure_git_credentials


def _stub_cfg(
    cfg,
    *,
    provider="",
    user="",
    token="",
    author_name="Nebula",
    author_email="nebula@noreply.invalid",
):
    cfg.git.provider = provider
    cfg.git.pat_user = user
    cfg.git.pat_token = token
    cfg.git.author_name = author_name
    cfg.git.author_email = author_email


def _called_with_args(mock_run, *expected_args):
    """True if any call's first positional arg is the expected command list."""
    return any(
        list(call.args[0]) == list(expected_args) for call in mock_run.call_args_list
    )


class TestConfigureGitCredentials(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())

    def tearDown(self):
        import shutil

        shutil.rmtree(self.home, ignore_errors=True)

    def test_skips_creds_when_provider_missing_but_sets_author(self):
        with (
            patch(
                "src.infrastructure.filesystem.git.git_credentials.system_config"
            ) as cfg,
            patch(
                "src.infrastructure.filesystem.git.git_credentials._cli.run"
            ) as mock_run,
        ):
            _stub_cfg(cfg, provider="", user="u", token="t")
            result = configure_git_credentials(home=self.home)

        self.assertFalse(result)
        self.assertFalse((self.home / ".git-credentials").exists())
        # Author identity is still set even when creds are skipped.
        self.assertTrue(
            _called_with_args(
                mock_run, "git", "config", "--global", "user.name", "Nebula"
            )
        )
        self.assertTrue(
            _called_with_args(
                mock_run,
                "git",
                "config",
                "--global",
                "user.email",
                "nebula@noreply.invalid",
            )
        )

    def test_skips_creds_when_user_env_unset(self):
        with (
            patch(
                "src.infrastructure.filesystem.git.git_credentials.system_config"
            ) as cfg,
            patch("src.infrastructure.filesystem.git.git_credentials._cli.run"),
        ):
            _stub_cfg(cfg, provider="github.com", user="", token="t")
            result = configure_git_credentials(home=self.home)
        self.assertFalse(result)

    def test_skips_creds_when_token_env_unset(self):
        with (
            patch(
                "src.infrastructure.filesystem.git.git_credentials.system_config"
            ) as cfg,
            patch("src.infrastructure.filesystem.git.git_credentials._cli.run"),
        ):
            _stub_cfg(cfg, provider="github.com", user="u", token="")
            result = configure_git_credentials(home=self.home)
        self.assertFalse(result)

    def test_writes_creds_file_when_all_set(self):
        with (
            patch(
                "src.infrastructure.filesystem.git.git_credentials.system_config"
            ) as cfg,
            patch(
                "src.infrastructure.filesystem.git.git_credentials._cli.run"
            ) as mock_run,
        ):
            _stub_cfg(cfg, provider="github.com", user="alice", token="ghp_secret")
            result = configure_git_credentials(home=self.home)

        self.assertTrue(result)
        creds = (self.home / ".git-credentials").read_text()
        self.assertEqual(creds, "https://alice:ghp_secret@github.com\n")
        self.assertEqual(
            oct((self.home / ".git-credentials").stat().st_mode)[-3:], "600"
        )
        self.assertTrue(
            _called_with_args(
                mock_run, "git", "config", "--global", "credential.helper", "store"
            )
        )
        self.assertTrue(
            _called_with_args(
                mock_run, "git", "config", "--global", "user.name", "Nebula"
            )
        )
        self.assertTrue(
            _called_with_args(
                mock_run,
                "git",
                "config",
                "--global",
                "user.email",
                "nebula@noreply.invalid",
            )
        )

    def test_overridable_author_identity(self):
        with (
            patch(
                "src.infrastructure.filesystem.git.git_credentials.system_config"
            ) as cfg,
            patch(
                "src.infrastructure.filesystem.git.git_credentials._cli.run"
            ) as mock_run,
        ):
            _stub_cfg(
                cfg,
                provider="github.com",
                user="u",
                token="t",
                author_name="CustomBot",
                author_email="bot@example.com",
            )
            configure_git_credentials(home=self.home)
        self.assertTrue(
            _called_with_args(
                mock_run, "git", "config", "--global", "user.name", "CustomBot"
            )
        )
        self.assertTrue(
            _called_with_args(
                mock_run, "git", "config", "--global", "user.email", "bot@example.com"
            )
        )


if __name__ == "__main__":
    unittest.main()
