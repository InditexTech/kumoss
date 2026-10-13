# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Boot-time git credential helper setup.

Sets the global commit author identity (always) and, when credentials
are available, writes ~/.git-credentials and enables git's `store`
credential helper so `git push` against the configured provider
authenticates without prompting. Idempotent — safe to call repeatedly.

Reads the user/token from the env vars named in `system_config.git`. If
any of provider/user/token is empty, logs a warning and skips the
credential write (push operations will fail at runtime, same as before).
The author identity is set regardless — git refuses to create a commit
without name + email.
"""

from __future__ import annotations

from pathlib import Path

from src.infrastructure.filesystem.cli import Cli
from src.shared.config.system_config import system_config
from src.shared.logger import logging

# `git config --global` writes to ~/.gitconfig regardless of cwd, but Cli
# requires a cwd. Use /tmp so we don't accidentally exercise any path-
# specific behaviour.
_cli = Cli(cwd="/tmp")


def configure_git_credentials(home: Path | None = None) -> bool:
    """Configure git: author identity (always) + ~/.git-credentials + store helper (when creds present).

    Returns True if credentials were written, False if only the author
    identity was set. `home` is overridable for tests.
    """
    _set_author_identity()

    provider = system_config.git.provider.value
    user = system_config.git.pat_user
    token = system_config.git.pat_token

    if not provider or not user or not token:
        logging.warning(
            "Git credentials not configured "
            + f"(provider={'set' if provider else 'unset'}, "
            + f"user={'set' if user else 'unset'}, "
            + f"token={'set' if token else 'unset'}). "
            + "`git push` will fail unless the operator provides a "
            + "pre-populated ~/.git-credentials, and pull requests cannot be "
            + "opened or merged."
        )
        return False

    home = home or Path.home()
    creds_file = home / ".git-credentials"
    _ = creds_file.write_text(f"https://{user}:{token}@{provider}\n")
    creds_file.chmod(0o600)

    _ = _cli.run(
        ["git", "config", "--global", "credential.helper", "store"],
        check=True,
    )
    logging.info(f"Git credentials configured for {provider}")
    return True


def _set_author_identity() -> None:
    """Stamp the global git user.name / user.email so commits are valid."""
    name = system_config.git.author_name
    email = system_config.git.author_email
    _ = _cli.run(["git", "config", "--global", "user.name", name], check=True)
    _ = _cli.run(["git", "config", "--global", "user.email", email], check=True)
    logging.info(f"Git author identity configured: {name} <{email}>")
