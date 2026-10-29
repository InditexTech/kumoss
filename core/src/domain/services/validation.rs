// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

//! The generate → commit → validate loop every round runs, and the
//! compliance audit of a validated plan.

use std::sync::Arc;

use futures::future::BoxFuture;
use indexmap::IndexMap;

use crate::domain::dto::{ComplianceCheckReport, ValidationResult};
use crate::domain::entities::{History, SharedSession, TurnAssistant, TurnUser};
use crate::domain::ports::{FileSystem, Git};
use crate::domain::services::artifact_storage::ArtifactStorageService;
use crate::domain::services::llm::LlmOrchestrationService;
use crate::domain::services::session::SessionService;
use crate::domain::services::template::{Render, TemplateOrchestrationService};
use crate::domain::services::tools::ToolOrchestrationService;
use crate::domain::value_objects::Conventions;
use crate::shared::config::SystemConfig;
use crate::shared::constants::{ContentType, OperationType, SessionStatus, ToolContext};
use crate::shared::error::{AppError, AppResult, ErrorKind};

/// Checks one attempt; its feedback is the next query.
pub type Validator<'a> = &'a (dyn Fn(History) -> BoxFuture<'a, AppResult<ValidationResult>> + Send + Sync);
/// Rewrites a failed attempt's feedback before it becomes the next query.
pub type Refiner<'a> = &'a (dyn Fn(String) -> BoxFuture<'a, AppResult<String>> + Send + Sync);

fn metadata(pairs: &[(&str, &str)]) -> IndexMap<String, String> {
    pairs
        .iter()
        .map(|(k, v)| ((*k).to_string(), (*v).to_string()))
        .collect()
}

#[derive(Clone)]
pub struct TerraformValidationService {
    git: Arc<dyn Git>,
    files: Arc<dyn FileSystem>,
    session: SessionService,
    templates: TemplateOrchestrationService,
    llm: LlmOrchestrationService,
    tools: ToolOrchestrationService,
    artifacts: ArtifactStorageService,
}

/// Parameters of one generation-validation loop.
pub struct LoopSpec<'a> {
    pub conventions: &'a Conventions,
    pub include_forbidden_actions: bool,
    pub operation_type: OperationType,
    pub max_iterations: i64,
}

impl TerraformValidationService {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        git: Arc<dyn Git>,
        files: Arc<dyn FileSystem>,
        session: SessionService,
        templates: TemplateOrchestrationService,
        llm: LlmOrchestrationService,
        tools: ToolOrchestrationService,
        artifacts: ArtifactStorageService,
    ) -> Self {
        Self {
            git,
            files,
            session,
            templates,
            llm,
            tools,
            artifacts,
        }
    }

    async fn upload_changed_files(&self, ctx: &SharedSession) -> AppResult<()> {
        let (id, round) = (ctx.id(), ctx.round_id());
        for name in self.git.get_changed_files(true, "AMD").await? {
            let content = self.git.show_diff(true, true, Some(&name)).await?;
            self.artifacts
                .store_code_change(
                    &id,
                    round,
                    &name,
                    &content,
                    ContentType::Text,
                    metadata(&[("new_file", "false")]),
                )
                .await?;
        }
        for name in self.git.get_untracked_files().await? {
            let content = match self.files.read_file(&name) {
                Ok(c) => c,
                Err(e) if e.kind != ErrorKind::Internal => {
                    tracing::warn!("Error reading file '{name}': {}", e.message);
                    continue;
                }
                Err(e) => return Err(e),
            };
            self.artifacts
                .store_code_change(
                    &id,
                    round,
                    &name,
                    &content,
                    ContentType::Text,
                    metadata(&[("new_file", "true")]),
                )
                .await?;
        }
        Ok(())
    }

    /// Run the generation and validation cycle: the last attempt's result
    /// when it succeeded, else `ValidationLoopExceeded` carrying it.
    pub async fn generate_and_validate(
        &self,
        q: &str,
        ctx: &SharedSession,
        spec: LoopSpec<'_>,
        validator: Validator<'_>,
        refine_feedback: Option<Refiner<'_>>,
    ) -> AppResult<ValidationResult> {
        let first_q = q.to_string();
        let mut q = q.to_string();
        let mut local_history = ctx.history();
        let mut result: Option<ValidationResult> = None;
        let branch = ctx.read(|c| c.branch_name.clone());
        for i in 0..spec.max_iterations.max(0) {
            tracing::debug!("Validation service {}/{}", i + 1, spec.max_iterations);
            self.session
                .update_status_with_llm(&q, SessionStatus::Generating, &local_history)
                .await?;

            let task_complete = self
                .llm
                .generate(
                    &q,
                    self.tools.get_available_tools(&[
                        ToolContext::ExternalInformation,
                        ToolContext::FileOperations,
                        ToolContext::WorkspaceInspection,
                    ])?,
                    Some(self.tools.get_sentinel_tool(ToolContext::GeneralTaskCompletion)?),
                    &self
                        .templates
                        .render(Render::IacGenerator {
                            operation_type: spec.operation_type,
                            resources: &spec.conventions.templates,
                            abbreviations: &spec.conventions.abbreviations,
                            include_forbidden_actions: spec.include_forbidden_actions,
                        })
                        .await?,
                    Some(&local_history),
                )
                .await?;
            let Some(result_map) = task_complete.result.as_object() else {
                return Err(AppError::internal(format!(
                    "'{}' object has no attribute 'get'",
                    if task_complete.result.is_null() {
                        "NoneType"
                    } else {
                        "list"
                    }
                )));
            };
            if let Some(summary) = result_map.get("summary").filter(|s| !s.is_null()) {
                local_history.append_turn(
                    TurnUser::Text(q.clone()),
                    TurnAssistant::Text(crate::shared::pyfmt::str_value(summary)),
                );
            } else {
                tracing::warn!("append_turn empty user or assistant msg, turn skipped");
            }

            self.upload_changed_files(ctx).await?;
            self.git.commit_and_push(&branch).await?;

            self.session
                .update_status_with_llm(
                    "Waiting for infrastructure as code to be validated.",
                    SessionStatus::Validating,
                    &local_history,
                )
                .await?;
            let attempt = validator(local_history.clone()).await?;
            let stdout = attempt.stdout();
            if !stdout.is_empty() {
                self.artifacts
                    .store_terraform_plan(
                        &ctx.id(),
                        ctx.round_id(),
                        &attempt.targets(),
                        &stdout,
                        ContentType::Text,
                        metadata(&[("type", "plan")]),
                    )
                    .await?;
            }
            if attempt.ok() {
                let last = local_history.get_last_turn()?.assistant.clone();
                let first = first_q.clone();
                ctx.write(|c| c.history.append_turn(TurnUser::Text(first), last));
                return Ok(attempt);
            }
            let feedback = attempt.feedback();
            result = Some(attempt);
            q = match refine_feedback {
                Some(refine) => refine(feedback).await?,
                None => feedback,
            };
        }
        let mut err = AppError::kind(ErrorKind::ValidationLoopExceeded, "Validation loop exceeded.", 422);
        err.result = result.map(Box::new);
        Err(err)
    }
}

#[derive(Clone)]
pub struct ComplianceCheckService {
    tools: ToolOrchestrationService,
    llm: LlmOrchestrationService,
    templates: TemplateOrchestrationService,
    artifacts: ArtifactStorageService,
    cfg: &'static SystemConfig,
}

impl ComplianceCheckService {
    pub fn new(
        tools: ToolOrchestrationService,
        llm: LlmOrchestrationService,
        templates: TemplateOrchestrationService,
        artifacts: ArtifactStorageService,
        cfg: &'static SystemConfig,
    ) -> Self {
        Self {
            tools,
            llm,
            templates,
            artifacts,
            cfg,
        }
    }

    pub async fn check(
        &self,
        ctx: &SharedSession,
        conventions: &Conventions,
        plan: &str,
    ) -> AppResult<ComplianceCheckReport> {
        if !self.cfg.orchestration.enable_compliance_checker {
            return Ok(ComplianceCheckReport::empty());
        }
        let first_user = ctx.read(|c| c.history.get_first_turn().map(|t| t.user.py_str()))?;
        let query = format!("The user request:\n{first_user}\n\nThe Terraform plan to audit:\n{plan}");
        let result = self
            .llm
            .generate(
                &query,
                self.tools.get_available_tools(&[ToolContext::ComplianceCheck])?,
                None,
                &self
                    .templates
                    .render(Render::ComplianceChecker {
                        resources: &conventions.templates,
                        abbreviations: &conventions.abbreviations,
                    })
                    .await?,
                None,
            )
            .await?;
        let report: ComplianceCheckReport =
            serde_json::from_value(result.result.clone()).map_err(|e| AppError::internal(e.to_string()))?;
        let content = serde_json::to_string(&result.result).map_err(|e| AppError::internal(e.to_string()))?;
        self.artifacts
            .store_compliance_check(
                &ctx.id(),
                ctx.round_id(),
                report.passed,
                &content,
                ContentType::Json,
                IndexMap::new(),
            )
            .await?;
        Ok(report)
    }
}
