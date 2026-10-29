// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

//! Terraform state backend for the workspaces handed to the IaC service.
//!
//! Renders `paths.backend_override_filename` into the workspace before
//! `init`, addressing the artifacts store's state bucket. Terraform merges
//! `*_override.tf` over the rest of the configuration and the injected
//! gitignore covers it. Static credentials are embedded when configured and
//! omitted otherwise, leaving the engine to resolve them the way any
//! backend does. State is keyed by the project id: clone directories are
//! per-call, so runs of the same project are brought together by something
//! that describes the project itself.

use std::path::Path;

use crate::shared::config::{StorageConfig, SystemConfig};
use crate::shared::constants::ObjectStorageProvider;
use crate::shared::error::{AppError, AppResult, ErrorKind};

pub struct TerraformBackend {
    project_id: String,
    cfg: &'static SystemConfig,
}

impl TerraformBackend {
    pub fn new(project_id: String, cfg: &'static SystemConfig) -> Self {
        Self { project_id, cfg }
    }

    pub fn state_key(&self) -> String {
        format!("{}/{}", self.project_id, self.cfg.storage.terraform_state_filename)
    }

    /// Write the override into `workspace_path`.
    pub fn apply(&self, workspace_path: &Path) -> AppResult<()> {
        let content = self.render()?;
        let target = workspace_path.join(&self.cfg.paths.backend_override_filename);
        if let Err(e) = std::fs::write(&target, content) {
            tracing::warn!("Could not write {}: {e}", target.display());
            return Err(AppError::kind(
                ErrorKind::TerraformBackend,
                "Error Terraform backend override render.",
                500,
            ));
        }
        tracing::info!(
            "Terraform state: {} bucket={} key={}",
            self.cfg.storage.provider.value(),
            self.cfg.storage.state_bucket(),
            self.state_key()
        );
        Ok(())
    }

    fn render(&self) -> AppResult<String> {
        let cfg = &self.cfg.storage;
        match cfg.provider {
            ObjectStorageProvider::Rustfs => Ok(self.s3_override(cfg, true)),
            ObjectStorageProvider::S3 => Ok(self.s3_override(cfg, false)),
            ObjectStorageProvider::StorageAccount => self.azurerm_override(cfg),
        }
    }

    fn s3_override(&self, cfg: &StorageConfig, custom_endpoint: bool) -> String {
        let mut lines = vec![
            format!("    bucket = \"{}\"", cfg.state_bucket()),
            format!("    key    = \"{}\"", self.state_key()),
            format!("    region = \"{}\"", cfg.region),
        ];
        let (access, secret) = (cfg.access_key(), cfg.secret_key());
        if !access.is_empty() && !secret.is_empty() {
            lines.extend([
                String::new(),
                format!("    access_key = \"{access}\""),
                format!("    secret_key = \"{secret}\""),
            ]);
        }
        if custom_endpoint {
            lines.extend(
                [
                    "",
                    "    endpoints = {",
                    &format!("      s3 = \"{}\"", cfg.endpoint_url),
                    "    }",
                    "",
                    "    use_path_style              = true",
                    "    skip_credentials_validation = true",
                    "    skip_region_validation      = true",
                    "    skip_requesting_account_id  = true",
                    "    skip_metadata_api_check     = true",
                    "    skip_s3_checksum            = true",
                    "    use_lockfile                = true",
                ]
                .map(str::to_string),
            );
        } else {
            lines.extend([String::new(), "    use_lockfile = true".to_string()]);
        }
        Self::wrap("s3", &lines)
    }

    fn azurerm_override(&self, cfg: &StorageConfig) -> AppResult<String> {
        let account = cfg.storage_account_name().map_err(|e| AppError::internal(e.0))?;
        let mut lines = vec![
            format!("    storage_account_name = \"{account}\""),
            format!("    container_name       = \"{}\"", cfg.state_bucket()),
            format!("    key                  = \"{}\"", self.state_key()),
        ];
        let key = cfg.account_key();
        if key.is_empty() {
            lines.push("    use_azuread_auth     = true".into());
        } else {
            lines.push(format!("    access_key           = \"{key}\""));
        }
        Ok(Self::wrap("azurerm", &lines))
    }

    fn wrap(backend_type: &str, lines: &[String]) -> String {
        format!(
            "terraform {{\n  backend \"{backend_type}\" {{\n{}\n  }}\n}}\n",
            lines.join("\n")
        )
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::shared::config::test_support::test_config;
    use serde_json::json;

    #[test]
    fn rustfs_override() {
        let cfg: &'static SystemConfig = Box::leak(Box::new(test_config(json!({}))));
        let backend = TerraformBackend::new("pid".into(), cfg);
        let out = backend.render().unwrap();
        assert!(out.starts_with("terraform {\n  backend \"s3\" {\n    bucket = \"kumoss-terraform-state\"\n    key    = \"pid/terraform.tfstate\"\n"));
        assert!(out.contains("      s3 = \"http://object-storage:9000\"\n"));
        assert!(out.ends_with("    use_lockfile                = true\n  }\n}\n"));
    }

    #[test]
    fn s3_override_without_keys() {
        let cfg: &'static SystemConfig = Box::leak(Box::new(test_config(json!({
            "storage": {"provider": "S3", "access_key_env": "KUMOSS_TEST_UNSET_A", "secret_key_env": "KUMOSS_TEST_UNSET_B"}
        }))));
        let out = TerraformBackend::new("pid".into(), cfg).render().unwrap();
        assert!(!out.contains("access_key"));
        assert!(out.ends_with("    region = \"us-east-1\"\n\n    use_lockfile = true\n  }\n}\n"));
    }
}
