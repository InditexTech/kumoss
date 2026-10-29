// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

//! Application services: the request filter, report generation, session
//! resolution and pull requests.

use std::sync::Arc;

use chrono::Utc;
use indexmap::IndexMap;
use serde_json::Value;
use uuid::Uuid;

use crate::application::iac_requests::IacRequest;
use crate::domain::dto::{PullRequestDto, ToolDefinition};
use crate::domain::entities::{History, SessionContext, SharedSession};
use crate::domain::ports::Git;
use crate::domain::services::artifact_storage::ArtifactStorageService;
use crate::domain::services::database::DatabaseService;
use crate::domain::services::llm::LlmOrchestrationService;
use crate::domain::services::session::SessionService;
use crate::domain::services::template::{Render, TemplateOrchestrationService};
use crate::domain::services::tools::ToolOrchestrationService;
use crate::shared::constants::{ContentType, OperationType, ReportType, SessionStatus, ToolContext};
use crate::shared::error::{AppError, AppResult, ErrorKind};
use crate::shared::pyfmt;

// --- request filter ---------------------------------------------------------------

#[derive(Clone)]
pub struct RequestsFilterService {
    session: SessionService,
    llm: LlmOrchestrationService,
    tools: ToolOrchestrationService,
    templates: TemplateOrchestrationService,
}

impl RequestsFilterService {
    pub fn new(
        session: SessionService,
        llm: LlmOrchestrationService,
        tools: ToolOrchestrationService,
        templates: TemplateOrchestrationService,
    ) -> Self {
        Self {
            session,
            llm,
            tools,
            templates,
        }
    }

    /// Decide whether `q` is actionable for the operation; a rejection
    /// joins the history and ends the round as `RequestFilter`.
    pub async fn filter(&self, q: &str, ctx: &SharedSession, operation_type: OperationType) -> AppResult<()> {
        let history = ctx.history();
        let response = self
            .llm
            .generate(
                q,
                self.tools.get_available_tools(&[ToolContext::WorkspaceInspection])?,
                Some(self.tools.get_sentinel_tool(ToolContext::RequestsFilter)?),
                &self.templates.render(Render::RequestsFilter { operation_type }).await?,
                Some(&history),
            )
            .await?;
        let rationale = pyfmt::str_value(response.require("explanation")?);
        let ok = truthy(response.require("status")?);
        if !ok {
            ctx.append_history(q, rationale.clone());
            return Err(AppError::kind(ErrorKind::RequestFilter, rationale, 400));
        }
        let _ = &self.session;
        Ok(())
    }
}

fn truthy(v: &Value) -> bool {
    match v {
        Value::Null => false,
        Value::Bool(b) => *b,
        Value::Number(n) => n.as_f64() != Some(0.0),
        Value::String(s) => !s.is_empty(),
        Value::Array(a) => !a.is_empty(),
        Value::Object(o) => !o.is_empty(),
    }
}

// --- reports ------------------------------------------------------------------------

#[derive(Clone)]
pub struct ReportService {
    llm: LlmOrchestrationService,
    tools: ToolOrchestrationService,
    templates: TemplateOrchestrationService,
    session: SessionService,
    artifacts: ArtifactStorageService,
}

impl ReportService {
    pub fn new(
        llm: LlmOrchestrationService,
        tools: ToolOrchestrationService,
        templates: TemplateOrchestrationService,
        session: SessionService,
        artifacts: ArtifactStorageService,
    ) -> Self {
        Self {
            llm,
            tools,
            templates,
            session,
            artifacts,
        }
    }

    /// Generate, store and return the structured report of a round.
    pub async fn generate_report(
        &self,
        ctx: &SharedSession,
        report_type: ReportType,
        content: &str,
    ) -> AppResult<Value> {
        let tool_index = match report_type {
            ReportType::Generate => 0,
            ReportType::Drift => 1,
            ReportType::Apply => 2,
            ReportType::Import => 3,
        };
        let msg = match report_type {
            ReportType::Apply => "Terraform apply finished. Generating report",
            ReportType::Import => "Terraform import processing finished. Generating report",
            _ => "Infrastructure successfully validated. Generating report",
        };
        self.session
            .update_status_with_llm(msg, SessionStatus::Report, &ctx.history())
            .await?;
        let sentinel: ToolDefinition = self
            .tools
            .get_available_tools(&[ToolContext::ReportGenerator])?
            .get(tool_index)
            .cloned()
            .ok_or_else(|| AppError::internal("list index out of range"))?;
        let response = self
            .llm
            .generate(
                content,
                self.select_tools(report_type)?,
                Some(sentinel),
                &self.templates.render(Render::ReportGenerator { report_type }).await?,
                None,
            )
            .await?;
        if !response.success {
            return Err(AppError::kind(
                ErrorKind::ReportGeneration,
                format!("report 'ReportType.{}' generation error.", report_type.name()),
                500,
            ));
        }
        let body = serde_json::to_string(&response.result).map_err(|e| AppError::internal(e.to_string()))?;
        self.artifacts
            .store_report(
                &ctx.id(),
                ctx.round_id(),
                report_type,
                &body,
                ContentType::Json,
                IndexMap::new(),
            )
            .await?;
        Ok(response.result)
    }

    pub async fn summarize_problem(&self, feedback: &str, history: &History) -> AppResult<String> {
        let prompt = self.templates.render(Render::StatusUpdate).await?;
        self.llm
            .generate_text(
                &format!("The IaC generated could not be validated: {feedback}"),
                &prompt,
                Some(history),
                false,
            )
            .await
    }

    /// The drift report reads the branch's own changes, not the web: its
    /// remediation is what `diff_history` returns. The plan and apply
    /// reports reason about a plan they already have and only need
    /// `web_search`, for pricing.
    fn select_tools(&self, report_type: ReportType) -> AppResult<Vec<ToolDefinition>> {
        let ctx = match report_type {
            ReportType::Drift => ToolContext::WorkspaceInspection,
            _ => ToolContext::ExternalInformation,
        };
        self.tools.get_available_tools(&[ctx])
    }
}

// --- session resolution -----------------------------------------------------------------

/// Resolves an incoming request into a session context: a first call
/// creates the session, an iteration call loads it.
#[derive(Clone)]
pub struct SessionOrchestrationService {
    db: DatabaseService,
}

impl SessionOrchestrationService {
    pub fn new(db: DatabaseService) -> Self {
        Self { db }
    }

    fn new_branch_name() -> String {
        format!("Kumoss/{}", Utc::now().format("%Y-%m-%d_%H%M%S"))
    }

    pub async fn resolve(
        &self,
        request: &IacRequest,
        operation: Option<OperationType>,
        user_pk: i64,
    ) -> AppResult<SessionContext> {
        if let (Some(first), Some(op)) = (request.first_call(), operation) {
            let sid = Uuid::new_v4();
            self.db
                .create_session(
                    &sid,
                    user_pk,
                    op,
                    &first.repo_uri,
                    first.terraform_provider,
                    &first.scope_id,
                    &Self::new_branch_name(),
                    &first.q,
                    first.iac_path.as_deref(),
                )
                .await?;
            return self.db.get_session_context(&sid).await;
        }
        let sid = request
            .session_id()
            .ok_or_else(|| AppError::internal("request carries no session id"))?;
        self.db.get_session_context(&sid).await
    }

    pub async fn acquire(&self, session_id: &Uuid) -> AppResult<()> {
        self.db.acquire_in_flight(session_id).await
    }

    pub async fn release(&self, session_id: &Uuid) -> AppResult<()> {
        self.db.release_in_flight(session_id).await
    }
}

// --- pull requests ------------------------------------------------------------------------

#[derive(Clone)]
pub struct PullRequestService {
    ctx: SessionContext,
    git: Arc<dyn Git>,
    llm: LlmOrchestrationService,
    tools: ToolOrchestrationService,
    templates: TemplateOrchestrationService,
    db: DatabaseService,
}

impl PullRequestService {
    pub fn new(
        ctx: SessionContext,
        git: Arc<dyn Git>,
        llm: LlmOrchestrationService,
        tools: ToolOrchestrationService,
        templates: TemplateOrchestrationService,
        db: DatabaseService,
    ) -> Self {
        Self {
            ctx,
            git,
            llm,
            tools,
            templates,
            db,
        }
    }

    pub async fn create_pr(&self) -> AppResult<PullRequestDto> {
        let response = self
            .llm
            .generate(
                "Create a pull request from this IaC session.",
                vec![self.tools.get_sentinel_tool(ToolContext::PrGenerator)?],
                None,
                &self
                    .templates
                    .render(Render::PrGenerator {
                        operation_type: self.ctx.operation,
                    })
                    .await?,
                Some(&self.ctx.history),
            )
            .await?;
        let Some(result) = response.result.as_object().filter(|_| response.success) else {
            let detail = match &response.error_message {
                Some(m) if !m.is_empty() => m.clone(),
                _ => pyfmt::str_value(&response.result),
            };
            return Err(AppError::new(format!("PR generation failed: {detail}"), 500));
        };
        let (Some(Value::String(title)), Some(Value::String(description))) =
            (result.get("title"), result.get("description"))
        else {
            return Err(AppError::new(
                format!(
                    "PR generation returned invalid payload: {}",
                    pyfmt::str_value(&response.result)
                ),
                500,
            ));
        };
        let dto = self
            .git
            .create_pr(&self.ctx.repo_uri, &self.ctx.branch_name, title, description)
            .await?;
        self.db.add_pull_request(&self.ctx.id, &dto.url, dto.id).await?;
        Ok(dto)
    }
}
