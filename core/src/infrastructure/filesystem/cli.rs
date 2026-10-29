// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

//! A small subprocess runner: one working directory, a timeout, captured
//! output. At most 20 commands run at once, the bound the Python core's
//! shared thread pool put on them.

use std::path::{Path, PathBuf};
use std::process::Stdio;
use std::sync::LazyLock;
use std::time::Duration;

use tokio::sync::Semaphore;

use crate::shared::error::{AppError, AppResult, ErrorKind};

static POOL: LazyLock<Semaphore> = LazyLock::new(|| Semaphore::new(20));

/// A finished command.
#[derive(Debug, Clone)]
pub struct Output {
    pub returncode: i32,
    pub stdout: Vec<u8>,
    pub stderr: Vec<u8>,
}

impl Output {
    pub fn stdout_str(&self) -> String {
        String::from_utf8_lossy(&self.stdout).into_owned()
    }

    /// stderr then stdout, decoded.
    pub fn combined(&self) -> String {
        let mut all = self.stderr.clone();
        all.extend_from_slice(&self.stdout);
        String::from_utf8_lossy(&all).into_owned()
    }
}

#[derive(Debug, Clone)]
pub struct Cli {
    cwd: PathBuf,
}

impl Cli {
    pub fn new(cwd: impl AsRef<Path>) -> Self {
        Self {
            cwd: cwd.as_ref().to_path_buf(),
        }
    }

    pub fn cwd(&self) -> &Path {
        &self.cwd
    }

    /// Run `command`; a non-zero exit is returned (and logged), a timeout or
    /// a command that could not start is an error.
    pub async fn execute(&self, command: &[&str], timeout: u64) -> AppResult<Output> {
        let _permit = POOL.acquire().await.map_err(|e| AppError::internal(e.to_string()))?;
        let joined = command.join(" ");
        let mut cmd = tokio::process::Command::new(command[0]);
        cmd.args(&command[1..])
            .current_dir(&self.cwd)
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .kill_on_drop(true);
        let child = cmd.spawn().map_err(|e| {
            let msg = format!("Unexpected error executing command: {joined} - {e}");
            tracing::error!("{msg}");
            AppError::kind(ErrorKind::Cli, msg, 500)
        })?;
        let output = match tokio::time::timeout(Duration::from_secs(timeout), child.wait_with_output()).await {
            Ok(Ok(o)) => o,
            Ok(Err(e)) => {
                let msg = format!("Unexpected error executing command: {joined} - {e}");
                tracing::error!("{msg}");
                return Err(AppError::kind(ErrorKind::Cli, msg, 500));
            }
            Err(_) => {
                let msg = format!("Command timed out after {timeout} seconds: {joined}");
                tracing::error!("{msg}");
                return Err(AppError::kind(ErrorKind::CliTimeout, msg, 408));
            }
        };
        let out = Output {
            returncode: output.status.code().unwrap_or(-1),
            stdout: output.stdout,
            stderr: output.stderr,
        };
        if out.returncode != 0 {
            tracing::warn!("Command returned non-zero exit code {}: {joined}", out.returncode);
            tracing::warn!("STDOUT: {}", out.combined());
        }
        Ok(out)
    }

    /// Like `execute`, but a non-zero exit is an error (`check=True`).
    pub async fn run_checked(&self, command: &[&str], timeout: u64) -> AppResult<Output> {
        let out = self.execute(command, timeout).await?;
        if out.returncode != 0 {
            let msg = format!(
                "Command failed with exit code {}: {}",
                out.returncode,
                command.join(" ")
            );
            tracing::error!("{msg}");
            tracing::error!("ERROR OUTPUT: {}", out.combined());
            return Err(AppError::kind(ErrorKind::Cli, msg, 500));
        }
        Ok(out)
    }
}
