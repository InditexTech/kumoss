// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

//! Boot-time git setup: the global commit author identity (always) and,
//! when credentials are available, `~/.git-credentials` with git's `store`
//! helper so `git push` authenticates without prompting. Idempotent.

use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};

use crate::infrastructure::filesystem::cli::Cli;
use crate::shared::config::SystemConfig;
use crate::shared::error::AppResult;

/// Returns whether credentials were written (false: only the author
/// identity was set). `home` is overridable for tests.
pub async fn configure_git_credentials(cfg: &SystemConfig, home: Option<&Path>) -> AppResult<bool> {
    // `git config --global` writes ~/.gitconfig regardless of cwd.
    let cli = Cli::new("/tmp");
    let name = &cfg.git.author_name;
    let email = &cfg.git.author_email;
    cli.run_checked(&["git", "config", "--global", "user.name", name], 300)
        .await?;
    cli.run_checked(&["git", "config", "--global", "user.email", email], 300)
        .await?;
    tracing::info!("Git author identity configured: {name} <{email}>");

    let provider = cfg.git.provider.value();
    let user = cfg.git.pat_user();
    let token = cfg.git.pat_token();
    if provider.is_empty() || user.is_empty() || token.is_empty() {
        let state = |v: &str| if v.is_empty() { "unset" } else { "set" };
        tracing::warn!(
            "Git credentials not configured (provider={}, user={}, token={}). `git push` will fail unless the operator provides a pre-populated ~/.git-credentials, and pull requests cannot be opened or merged.",
            state(provider),
            state(&user),
            state(&token)
        );
        return Ok(false);
    }
    let home: PathBuf = match home {
        Some(h) => h.to_path_buf(),
        None => std::env::var("HOME")
            .map(PathBuf::from)
            .unwrap_or_else(|_| PathBuf::from("/root")),
    };
    let creds = home.join(".git-credentials");
    std::fs::write(&creds, format!("https://{user}:{token}@{provider}\n"))
        .map_err(|e| crate::shared::error::AppError::internal(e.to_string()))?;
    std::fs::set_permissions(&creds, std::fs::Permissions::from_mode(0o600))
        .map_err(|e| crate::shared::error::AppError::internal(e.to_string()))?;
    cli.run_checked(&["git", "config", "--global", "credential.helper", "store"], 300)
        .await?;
    tracing::info!("Git credentials configured for {provider}");
    Ok(true)
}
