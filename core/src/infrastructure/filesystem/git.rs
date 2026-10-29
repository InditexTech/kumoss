// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

//! `Git` over the git CLI, rooted at one working copy.

use std::path::{Path, PathBuf};
use std::sync::{LazyLock, Mutex};

use async_trait::async_trait;
use regex::Regex;
use sha2::{Digest, Sha256};

use crate::domain::dto::PullRequestDto;
use crate::domain::ports::Git;
use crate::infrastructure::filesystem::cli::{Cli, Output};
use crate::infrastructure::filesystem::providers::GitProvider;
use crate::infrastructure::tools::realpath;
use crate::shared::config::SystemConfig;
use crate::shared::error::{AppError, AppResult, ErrorKind};
use crate::shared::pyfmt;
use crate::shared::urls::safe_uri;

static SYMREF: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"ref:\s+refs/heads/(\S+)\s+HEAD").unwrap());

pub struct GitUtils {
    uri: String,
    provider: GitProvider,
    cli: Cli,
    error_msg: Mutex<String>,
}

impl GitUtils {
    pub fn new(uri: &str, cwd: Option<&Path>, cfg: &'static SystemConfig) -> Self {
        let cwd: PathBuf = cwd
            .map(Path::to_path_buf)
            .unwrap_or_else(|| cfg.paths.upload_folder.clone());
        let cwd = realpath(&std::path::absolute(&cwd).unwrap_or(cwd));
        Self {
            uri: uri.to_string(),
            provider: GitProvider::new(cfg.git.provider, cfg),
            cli: Cli::new(cwd),
            error_msg: Mutex::new(String::new()),
        }
    }

    fn set_error(&self, msg: String) {
        *self.error_msg.lock().expect("error lock") = msg;
    }

    fn handle_return_code(&self, out: &Output) -> bool {
        if out.returncode != 0 {
            let msg = out.combined();
            tracing::error!("{msg}");
            self.set_error(msg);
            return false;
        }
        true
    }

    async fn run(&self, cmd: &[&str]) -> AppResult<Output> {
        self.cli.execute(cmd, 300).await
    }

    fn fail(&self, code: u16, prefix: &str) -> AppError {
        AppError::new(format!("{prefix}{}", self.error_msg()), code)
    }

    async fn default_branch_commit_id(&self) -> AppResult<String> {
        let default_branch = self.get_default_branch(false).await?;
        let merge_base = ["git", "merge-base", default_branch.as_str(), "HEAD"];
        let mut out = self.run(&merge_base).await?;
        if out.returncode != 0 && self.is_shallow_repository().await? {
            // Shallow clones truncate history, so the branches can look
            // disconnected; fetch the full history and retry once.
            let current = self.show_current_branch().await?;
            if !self.fetch_unshallow(&[&default_branch, &current]).await? {
                return Err(self.fail(500, "Git error when unshallowing: "));
            }
            out = self.run(&merge_base).await?;
        }
        if !self.handle_return_code(&out) {
            return Err(self.fail(500, "Git error when merging base: "));
        }
        Ok(pyfmt::strip(&out.stdout_str()).to_string())
    }

    async fn is_shallow_repository(&self) -> AppResult<bool> {
        let out = self.run(&["git", "rev-parse", "--is-shallow-repository"]).await?;
        Ok(out.returncode == 0 && pyfmt::strip(&out.stdout_str()) == "true")
    }

    async fn fetch_unshallow(&self, branches: &[&str]) -> AppResult<bool> {
        let mut refspecs: Vec<String> = Vec::new();
        for b in branches.iter().filter(|b| !b.is_empty()) {
            let spec = format!("refs/heads/{b}:refs/remotes/origin/{b}");
            if !refspecs.contains(&spec) {
                refspecs.push(spec);
            }
        }
        let mut cmd: Vec<&str> = vec!["git", "fetch", "--unshallow", "origin"];
        cmd.extend(refspecs.iter().map(String::as_str));
        tracing::debug!("{cmd:?}");
        let out = self.run(&cmd).await?;
        Ok(self.handle_return_code(&out))
    }

    async fn checkout_branch(&self, target: &str) -> AppResult<bool> {
        if self.show_current_branch().await? == target {
            return Ok(true);
        }
        if self.check_branch_exists(target).await? {
            let refspec = format!("refs/heads/{target}:refs/remotes/origin/{target}");
            let cmd = ["git", "fetch", "--depth", "1", "origin", refspec.as_str()];
            tracing::debug!("{cmd:?}");
            if !self.handle_return_code(&self.run(&cmd).await?) {
                return Ok(false);
            }
            let remote = format!("refs/remotes/origin/{target}");
            let cmd = ["git", "checkout", "-B", target, remote.as_str()];
            tracing::debug!("{cmd:?}");
            return Ok(self.handle_return_code(&self.run(&cmd).await?));
        }
        tracing::debug!("git new branch checkout {target}");
        let default_branch = self.get_default_branch(false).await?;
        let out = self
            .run(&["git", "checkout", "-b", target, default_branch.as_str()])
            .await?;
        Ok(self.handle_return_code(&out))
    }

    async fn show_current_branch(&self) -> AppResult<String> {
        let out = self.run(&["git", "branch", "--show-current"]).await?;
        Ok(out.stdout_str().trim_matches('\n').to_string())
    }

    async fn check_branch_exists(&self, branch: &str) -> AppResult<bool> {
        let out = match self
            .cli
            .execute(&["git", "ls-remote", "--exit-code", "--heads", "origin", branch], 20)
            .await
        {
            Ok(o) => o,
            Err(e) if e.is(ErrorKind::CliTimeout) => return Err(AppError::repository_unreachable(502)),
            Err(e) => return Err(e),
        };
        match out.returncode {
            0 => Ok(true),
            2 => Ok(false),
            _ => {
                self.handle_return_code(&out);
                Err(AppError::repository_unreachable(502))
            }
        }
    }

    async fn are_there_changes(&self) -> AppResult<bool> {
        let out = self.run(&["git", "status", "--porcelain"]).await?;
        let status = pyfmt::strip(&out.stdout_str()).to_string();
        tracing::info!("git status {status}");
        Ok(!status.is_empty())
    }

    async fn commit_changes(&self) -> AppResult<bool> {
        if !self.handle_return_code(&self.run(&["git", "add", "-A"]).await?) {
            return Ok(false);
        }
        if self.are_there_changes().await? {
            tracing::info!("git changes commited");
            return Ok(self.handle_return_code(&self.run(&["git", "commit", "-m", "Kumoss changes"]).await?));
        }
        Ok(true)
    }

    async fn push_commits(&self, branch: &str) -> AppResult<bool> {
        tracing::info!("git push origin/{branch}");
        Ok(self.handle_return_code(&self.run(&["git", "push", "--set-upstream", "origin", branch]).await?))
    }
}

#[async_trait]
impl Git for GitUtils {
    fn error_msg(&self) -> String {
        self.error_msg.lock().expect("error lock").clone()
    }

    async fn ls_remote(&self) -> bool {
        tracing::info!("git ls-remote {}", self.uri);
        match self
            .cli
            .execute(&["git", "ls-remote", "--exit-code", "--", &self.uri], 20)
            .await
        {
            Ok(out) => self.handle_return_code(&out),
            Err(e) => {
                self.set_error(e.message);
                false
            }
        }
    }

    async fn clone_repository(&self, repo_url: &str, repository_name: &str, extra_args: &[&str], timeout: u64) -> bool {
        let mut cmd: Vec<&str> = vec!["git", "clone", "--depth", "1"];
        cmd.extend_from_slice(extra_args);
        cmd.extend(["--", repo_url, repository_name]);
        let safe = safe_uri(repo_url);
        let out = match self.cli.execute(&cmd, timeout).await {
            Ok(o) => o,
            Err(e) => {
                if e.is(ErrorKind::CliTimeout) {
                    tracing::error!("git clone timed out for {safe}");
                }
                self.set_error(e.message);
                return false;
            }
        };
        if !self.handle_return_code(&out) {
            tracing::error!(
                "git clone failed for {safe}{}",
                if repo_url != safe {
                    " (original url included credentials)"
                } else {
                    ""
                }
            );
            return false;
        }
        tracing::info!("git clone {safe}");
        true
    }

    async fn ls_tree(&self, cwd: &Path) -> AppResult<Vec<String>> {
        let out = Cli::new(cwd)
            .execute(&["git", "ls-tree", "-r", "--name-only", "HEAD"], 30)
            .await?;
        if !self.handle_return_code(&out) {
            return Err(AppError::new(format!("git ls-tree failed: {}", self.error_msg()), 502));
        }
        Ok(pyfmt::splitlines(&out.stdout_str())
            .into_iter()
            .map(str::to_string)
            .collect())
    }

    async fn push_branch(&self, branch: &str) -> bool {
        tracing::info!("git push --set-upstream origin {branch}");
        match self.run(&["git", "push", "--set-upstream", "origin", branch]).await {
            Ok(out) => self.handle_return_code(&out),
            Err(_) => false,
        }
    }

    async fn checkout(&self, branch: &str) -> AppResult<()> {
        if !self.checkout_branch(branch).await? {
            return Err(AppError::new(self.error_msg(), 500));
        }
        Ok(())
    }

    async fn commit_and_push(&self, branch: &str) -> AppResult<()> {
        if !self.commit_changes().await? || !self.push_commits(branch).await? {
            return Err(AppError::new(self.error_msg(), 500));
        }
        Ok(())
    }

    async fn create_pr(
        &self,
        repository_url: &str,
        head_branch: &str,
        title: &str,
        description: &str,
    ) -> AppResult<PullRequestDto> {
        let base = self.get_default_branch(true).await?;
        self.provider
            .create_pr(repository_url, head_branch, &base, title, description)
            .await
    }

    async fn complete_pr(&self, pr_id: i64) -> AppResult<()> {
        self.provider.complete_pr(&self.uri, pr_id).await
    }

    async fn get_default_branch(&self, ls_remote: bool) -> AppResult<String> {
        let cmd: Vec<&str> = if ls_remote {
            vec!["git", "ls-remote", "--symref", &self.uri, "HEAD"]
        } else {
            vec!["git", "rev-parse", "--abbrev-ref", "origin/HEAD"]
        };
        if ls_remote {
            tracing::debug!("{:?}", ["git", "ls-remote", "--symref", "<repository>", "HEAD"]);
        } else {
            tracing::debug!("{cmd:?}");
        }
        let out = match self.run(&cmd).await {
            Ok(o) => o,
            Err(e) if e.is(ErrorKind::CliTimeout) => return Err(AppError::repository_unreachable(502)),
            Err(e) => return Err(e),
        };
        if !self.handle_return_code(&out) {
            if ls_remote {
                return Err(AppError::repository_unreachable(502));
            }
            return Err(AppError::new(self.error_msg(), 502));
        }
        let stdout = out.stdout_str();
        if ls_remote {
            return match SYMREF.captures(&stdout) {
                Some(c) => Ok(c[1].to_string()),
                None => Err(AppError::new("No match git default branch ls-remote", 500)),
            };
        }
        Ok(pyfmt::strip(&stdout).rsplit('/').next().unwrap_or("").to_string())
    }

    async fn get_workspace_revision(&self) -> AppResult<String> {
        let cmd = ["git", "status", "--porcelain=v2", "--branch", "--untracked-files=all"];
        tracing::debug!("{cmd:?}");
        let out = self.run(&cmd).await?;
        if !self.handle_return_code(&out) {
            return Err(AppError::new(
                format!("Git error when reading the workspace revision: {}", self.error_msg()),
                502,
            ));
        }
        Ok(hex::encode(Sha256::digest(&out.stdout)))
    }

    async fn get_untracked_files(&self) -> AppResult<Vec<String>> {
        let cmd = ["git", "--no-pager", "ls-files", "--others", "--exclude-standard"];
        tracing::debug!("{cmd:?}");
        let out = self.run(&cmd).await?;
        if !self.handle_return_code(&out) {
            return Err(self.fail(500, "Git error when fetching changed files: "));
        }
        Ok(pyfmt::splitlines(pyfmt::strip(&out.stdout_str()))
            .into_iter()
            .map(str::to_string)
            .collect())
    }

    async fn get_changed_files(&self, working_tree: bool, diff_filter: &str) -> AppResult<Vec<String>> {
        let filter = format!("--diff-filter={diff_filter}");
        let mut cmd: Vec<String> = [
            "git",
            "--no-pager",
            "diff",
            "--name-only",
            &filter,
            "--relative",
            "HEAD",
        ]
        .map(str::to_string)
        .to_vec();
        if !working_tree {
            cmd.insert(6, self.default_branch_commit_id().await?);
        }
        tracing::debug!("{cmd:?}");
        let args: Vec<&str> = cmd.iter().map(String::as_str).collect();
        let out = self.run(&args).await?;
        if !self.handle_return_code(&out) {
            return Err(self.fail(500, "Git error when fetching changed files: "));
        }
        Ok(pyfmt::splitlines(pyfmt::strip(&out.stdout_str()))
            .into_iter()
            .map(str::to_string)
            .collect())
    }

    async fn show_diff(&self, working_tree: bool, full_content: bool, file_path: Option<&str>) -> AppResult<String> {
        let mut cmd: Vec<String> = [
            "git",
            "--no-pager",
            "diff",
            "--no-color",
            "--find-renames",
            "--no-prefix",
            "--ignore-space-change",
            "--relative",
            "HEAD",
        ]
        .map(str::to_string)
        .to_vec();
        if full_content {
            cmd.insert(3, "--unified=1000".into());
        }
        if !working_tree {
            let head = cmd.iter().position(|c| c == "HEAD").unwrap_or(cmd.len());
            cmd.insert(head, self.default_branch_commit_id().await?);
        }
        if let Some(path) = file_path.filter(|p| !p.is_empty()) {
            cmd.push("--".into());
            cmd.push(path.into());
        }
        tracing::debug!("{cmd:?}");
        let args: Vec<&str> = cmd.iter().map(String::as_str).collect();
        let out = self.run(&args).await?;
        if !self.handle_return_code(&out) {
            return Err(AppError::new(self.error_msg(), 502));
        }
        Ok(out.stdout_str())
    }
}
