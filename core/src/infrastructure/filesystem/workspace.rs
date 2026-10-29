// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

//! Per-call git workspace lifecycle.
//!
//! A workspace is `{base}/{session_id}/{call_id}/` and exists only for the
//! duration of one use-case call: on success the branch is pushed and the
//! directory removed; on failure it is removed unchanged. A session also
//! owns one pinned slot, `{base}/{session_id}/pinned/`: the workspace of the
//! last successful generate/drift round, renamed there at round end so its
//! validated plan can be applied by a later apply call.

use std::path::{Path, PathBuf};

use uuid::Uuid;

use crate::domain::ports::{FileSystem, Git};
use crate::infrastructure::filesystem::fs::FileSystemUtils;
use crate::infrastructure::filesystem::git::GitUtils;
use crate::infrastructure::tools::realpath;
use crate::shared::config::SystemConfig;
use crate::shared::error::{AppError, AppResult, ErrorKind};

const TERRAFORM_GITIGNORE: &str = include_str!("../../../resources/terraform.gitignore");
const REUSE_MARKER: &str = "INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)";

#[derive(Clone)]
pub struct WorkspaceService {
    base: Option<PathBuf>,
    cfg: &'static SystemConfig,
}

impl WorkspaceService {
    pub fn new(cfg: &'static SystemConfig) -> Self {
        Self { base: None, cfg }
    }

    pub fn with_base(cfg: &'static SystemConfig, base: PathBuf) -> Self {
        Self { base: Some(base), cfg }
    }

    fn base(&self) -> PathBuf {
        self.base
            .clone()
            .unwrap_or_else(|| self.cfg.paths.upload_folder.clone())
    }

    fn add_terraform_gitignore(&self, path: &Path) -> AppResult<()> {
        let utils = FileSystemUtils::new(path, &self.cfg.paths.backend_override_filename);
        let target = utils.project_root().join(".gitignore");
        let mut content = TERRAFORM_GITIGNORE.to_string();
        if target.exists() {
            let existing = std::fs::read_to_string(&target).map_err(|e| AppError::internal(e.to_string()))?;
            if existing.contains(REUSE_MARKER) {
                return Ok(());
            }
            content = format!("{}\n\n{content}", existing.trim_end_matches('\n'));
        }
        utils.write_file(".gitignore", &content, false)
    }

    /// Verify the URI is reachable; `RepositoryUnreachable` (400) otherwise.
    pub async fn validate_uri(&self, repo_uri: &str) -> AppResult<()> {
        let git = GitUtils::new(repo_uri, Some(&std::env::temp_dir()), self.cfg);
        if !git.ls_remote().await {
            tracing::warn!("git ls-remote failed for {repo_uri}: {}", git.error_msg());
            return Err(AppError::repository_unreachable(400));
        }
        Ok(())
    }

    /// Shallow-clone into the per-call directory, check out the session
    /// branch and push it.
    pub async fn setup_call_dir(&self, session_id: &Uuid, repo_uri: &str, branch: &str) -> AppResult<PathBuf> {
        let call_id = Uuid::new_v4();
        let parent = self.base().join(session_id.to_string());
        let call_dir = parent.join(call_id.to_string());
        std::fs::create_dir_all(&parent).map_err(|e| AppError::internal(e.to_string()))?;

        // The clone lands at `cwd / repository_name`.
        let git = GitUtils::new(repo_uri, Some(&parent), self.cfg);
        if !git.clone_repository(repo_uri, &call_id.to_string(), &[], 300).await {
            return Err(AppError::repository_unreachable(500));
        }
        if let Err(e) = self.add_terraform_gitignore(&call_dir) {
            tracing::warn!("terraform gitignore couldn't be created: {}", e.message);
        }
        let git = GitUtils::new(repo_uri, Some(&call_dir), self.cfg);
        git.checkout(branch).await?;
        git.commit_and_push(branch).await?;
        Ok(call_dir)
    }

    /// The IaC root of a call directory. Symlinks are resolved: the root must
    /// be an existing directory inside the clone, so a committed link cannot
    /// widen the scope of the tools working in it.
    pub fn iac_root(&self, call_dir: &Path, iac_path: Option<&str>) -> AppResult<PathBuf> {
        let clone = realpath(call_dir);
        let root = realpath(&clone.join(iac_path.unwrap_or("")));
        if !root.starts_with(&clone) || !root.is_dir() {
            return Err(AppError::kind(
                ErrorKind::InvalidIacPath,
                format!(
                    "iac_path '{}' is not a directory inside the repository",
                    iac_path.unwrap_or("None")
                ),
                400,
            ));
        }
        Ok(root)
    }

    /// Remove the per-call directory. Idempotent.
    pub fn cleanup(&self, call_dir: Option<&Path>) {
        if let Some(dir) = call_dir {
            let _ = std::fs::remove_dir_all(dir);
        }
    }

    /// Path of the session's pinned workspace slot (may not exist).
    pub fn pinned_dir(&self, session_id: &Uuid) -> PathBuf {
        self.base().join(session_id.to_string()).join("pinned")
    }

    /// Promote a validated workspace into the pinned slot, replacing any
    /// previous pin: latest successful round wins.
    pub fn pin_workspace(&self, session_id: &Uuid, call_dir: &Path) -> AppResult<()> {
        let pinned = self.pinned_dir(session_id);
        let _ = std::fs::remove_dir_all(&pinned);
        std::fs::rename(call_dir, &pinned)
            .map_err(|e| AppError::internal(crate::infrastructure::filesystem::oserror_repr(&e)))
    }

    /// Remove the session's pinned slot. Idempotent.
    pub fn discard_pinned(&self, session_id: &Uuid) {
        let _ = std::fs::remove_dir_all(self.pinned_dir(session_id));
    }

    /// The session's single pinned plan artifact, or `None`.
    pub fn pinned_plan_path(&self, session_id: &Uuid) -> Option<PathBuf> {
        let pinned = self.pinned_dir(session_id);
        let plan = pinned.join(&self.cfg.paths.session_plan_filename);
        if !pinned.is_dir() || !plan.is_file() {
            return None;
        }
        Some(plan)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::shared::config::test_support::test_config;
    use serde_json::json;

    fn service(base: &Path) -> WorkspaceService {
        let cfg: &'static SystemConfig = Box::leak(Box::new(test_config(json!({}))));
        WorkspaceService::with_base(cfg, base.to_path_buf())
    }

    #[test]
    fn iac_root_must_stay_inside() {
        let dir = tempfile::tempdir().unwrap();
        let ws = service(dir.path());
        let call = dir.path().join("call");
        std::fs::create_dir_all(call.join("envs/dev")).unwrap();
        assert_eq!(
            ws.iac_root(&call, Some("envs/dev")).unwrap(),
            realpath(&call.join("envs/dev"))
        );
        assert_eq!(ws.iac_root(&call, None).unwrap(), realpath(&call));
        let err = ws.iac_root(&call, Some("../")).unwrap_err();
        assert_eq!(err.message, "iac_path '../' is not a directory inside the repository");
        std::os::unix::fs::symlink("/etc", call.join("escape")).unwrap();
        assert!(ws.iac_root(&call, Some("escape")).is_err());
    }

    #[test]
    fn pinning_lifecycle() {
        let dir = tempfile::tempdir().unwrap();
        let ws = service(dir.path());
        let sid = Uuid::new_v4();
        let call = dir.path().join(sid.to_string()).join("c1");
        std::fs::create_dir_all(&call).unwrap();
        assert!(ws.pinned_plan_path(&sid).is_none());
        std::fs::write(call.join("session.plan"), b"x").unwrap();
        ws.pin_workspace(&sid, &call).unwrap();
        assert!(ws.pinned_plan_path(&sid).is_some());
        ws.discard_pinned(&sid);
        assert!(ws.pinned_plan_path(&sid).is_none());
    }

    #[test]
    fn gitignore_appended_once() {
        let dir = tempfile::tempdir().unwrap();
        let ws = service(dir.path());
        std::fs::write(dir.path().join(".gitignore"), "custom\n\n").unwrap();
        ws.add_terraform_gitignore(dir.path()).unwrap();
        let first = std::fs::read_to_string(dir.path().join(".gitignore")).unwrap();
        assert!(first.starts_with("custom\n\n# SPDX"));
        ws.add_terraform_gitignore(dir.path()).unwrap();
        assert_eq!(std::fs::read_to_string(dir.path().join(".gitignore")).unwrap(), first);
    }
}
