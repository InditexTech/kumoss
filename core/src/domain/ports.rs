// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

//! Interfaces the domain depends on; infrastructure implements them.

use std::path::{Path, PathBuf};

use async_trait::async_trait;
use indexmap::IndexMap;
use serde_json::Value;

use crate::domain::dto::{
    LlmResponse, PullRequestDto, TerraformApplyDto, TerraformDiscoveryDto, TerraformDriftDto,
    TerraformImportResourceDto, TerraformPlanDto, ToolCall, ToolDefinition, ToolResult,
};
use crate::domain::entities::{History, TurnUser};
use crate::domain::value_objects::PlanRef;
use crate::shared::constants::{TerraformProvider, ToolContext};
use crate::shared::error::AppResult;

/// One inference call. `notice` is a harness note sent as a user message
/// after `msg`, for this call only (it is not part of the history).
#[derive(Debug, Clone, Copy)]
pub struct InferenceRequest<'a> {
    pub msg: &'a TurnUser,
    pub system_prompt: Option<&'a str>,
    pub tools: Option<&'a [ToolDefinition]>,
    pub history: Option<&'a History>,
    pub thinking: bool,
    pub notice: Option<&'a str>,
}

impl<'a> InferenceRequest<'a> {
    pub fn new(msg: &'a TurnUser) -> Self {
        Self {
            msg,
            system_prompt: None,
            tools: None,
            history: None,
            thinking: false,
            notice: None,
        }
    }
}

#[async_trait]
pub trait LlmProvider: Send + Sync {
    fn model(&self) -> &str;

    /// Create a message, with tool calling when `tools` is given.
    async fn inference(&self, request: InferenceRequest<'_>) -> AppResult<LlmResponse>;
}

/// Object metadata, in insertion order.
pub type ObjectMetadata = IndexMap<String, String>;

/// Provider-agnostic blob store keyed by opaque string keys.
///
/// Implementations translate every provider failure into `ObjectNotFound`
/// (404) / `ObjectStorageUnavailable` (503) / `ObjectStorage` (500)
/// errors; no SDK error escapes.
#[async_trait]
pub trait ObjectStorage: Send + Sync {
    /// Create the backing bucket/container if missing. Idempotent.
    async fn ensure_bucket(&self) -> AppResult<()>;

    /// Store `data` at `key` (no scheme, no bucket), last write wins.
    async fn put(&self, key: &str, data: Vec<u8>, content_type: &str, metadata: &ObjectMetadata) -> AppResult<()>;

    /// Prefix this store prepends to metadata keys on the way out, so a
    /// browser reading metadata off a presigned URL knows what to ask for.
    fn metadata_header_prefix(&self) -> &'static str;

    /// Full object body. `ObjectNotFound` when the key does not exist.
    async fn get(&self, key: &str) -> AppResult<Vec<u8>>;

    async fn exists(&self, key: &str) -> AppResult<bool>;

    /// Deleting a missing key is a no-op.
    async fn delete(&self, key: &str) -> AppResult<()>;

    /// Browser-fetchable, time-limited GET URL; `expires_in` defaults to the
    /// configured expiry.
    async fn presigned_get_url(&self, key: &str, expires_in: Option<u64>) -> AppResult<String>;
}

/// Tool-oriented filesystem rooted at the IaC root of a workspace.
pub trait FileSystem: Send + Sync {
    fn project_root(&self) -> PathBuf;

    /// Names of the entries managed by Kumoss, hidden from the tools.
    fn protected_names(&self) -> Vec<String>;

    fn write_file(&self, target_file: &str, content: &str, is_safe: bool) -> AppResult<()>;

    fn replace_in_file(&self, target_file: &str, search_replace_blocks: &str) -> AppResult<()>;

    fn delete_file(&self, target_file: &str) -> AppResult<()>;

    fn read_file(&self, target_file: &str) -> AppResult<String>;

    fn list_directory(&self, relative_path: &str) -> AppResult<Vec<PathBuf>>;

    fn search_files(
        &self,
        query: &str,
        include_pattern: Option<&str>,
        exclude_pattern: Option<&str>,
        case_sensitive: bool,
    ) -> AppResult<Vec<String>>;
}

/// Git operations on one working copy.
#[async_trait]
pub trait Git: Send + Sync {
    fn error_msg(&self) -> String;

    async fn ls_remote(&self) -> bool;

    async fn clone_repository(&self, repo_url: &str, repository_name: &str, extra_args: &[&str], timeout: u64) -> bool;

    async fn ls_tree(&self, cwd: &Path) -> AppResult<Vec<String>>;

    async fn push_branch(&self, branch: &str) -> bool;

    async fn checkout(&self, branch: &str) -> AppResult<()>;

    async fn commit_and_push(&self, branch: &str) -> AppResult<()>;

    async fn create_pr(
        &self,
        repository_url: &str,
        head_branch: &str,
        title: &str,
        description: &str,
    ) -> AppResult<PullRequestDto>;

    async fn complete_pr(&self, pr_id: i64) -> AppResult<()>;

    async fn get_default_branch(&self, ls_remote: bool) -> AppResult<String>;

    /// A fingerprint of the working tree: the checked-out commit plus any
    /// uncommitted or untracked change on top of it.
    async fn get_workspace_revision(&self) -> AppResult<String>;

    async fn get_untracked_files(&self) -> AppResult<Vec<String>>;

    async fn get_changed_files(&self, working_tree: bool, diff_filter: &str) -> AppResult<Vec<String>>;

    async fn show_diff(&self, working_tree: bool, full_content: bool, file_path: Option<&str>) -> AppResult<String>;
}

/// Plan, read drift, apply and import through the IaC service.
#[async_trait]
pub trait Terraform: Send + Sync {
    async fn plan(&self, targets: &[String]) -> AppResult<TerraformPlanDto>;

    async fn drift(&self, plan: &PlanRef) -> AppResult<TerraformDriftDto>;

    async fn apply(&self) -> AppResult<TerraformApplyDto>;

    async fn state_resource_ids(&self) -> AppResult<TerraformDiscoveryDto>;

    async fn scope_resource_ids(
        &self,
        scope_id: &str,
        terraform_provider: TerraformProvider,
    ) -> AppResult<TerraformDiscoveryDto>;

    async fn import_resource(&self, address: &str, resource_id: &str) -> AppResult<TerraformImportResourceDto>;
}

/// Managing and executing tools.
#[async_trait]
pub trait ToolRegistry: Send + Sync {
    fn get_available_tools(&self, context: ToolContext) -> AppResult<Vec<ToolDefinition>>;

    fn get_tool_definition(&self, tool_name: &str) -> AppResult<ToolDefinition>;

    async fn execute_tool(&self, call: &ToolCall) -> ToolResult;

    fn validate_tool_parameters(&self, tool_name: &str, parameters: &Value) -> bool;
}
