// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

//! The four round handlers: generate (CRUD), drift, apply and import.
//!
//! Every round closes by saving the session (chat reply + histories), even
//! when it fails; like a Python `finally`, an error while saving replaces
//! the round's own outcome.

use std::future::Future;
use std::sync::{Arc, Mutex};

use futures::FutureExt;
use serde_json::{Value, json};

use crate::application::drift_import::{TerraformDriftService, TerraformImportService};
use crate::application::services::{ReportService, RequestsFilterService};
use crate::domain::dto::{AttemptSet, TerraformApplyReport, TerraformImportDto, TerraformPlanReport, ValidationResult};
use crate::domain::entities::{History, SharedSession};
use crate::domain::ports::Terraform;
use crate::domain::services::database::DatabaseService;
use crate::domain::services::session::SessionService;
use crate::domain::services::targets::{ImportTargets, TerraformImportAddressService, TerraformTargetService};
use crate::domain::services::task::TaskService;
use crate::domain::services::template::TemplateOrchestrationService;
use crate::domain::services::validation::{ComplianceCheckService, LoopSpec, TerraformValidationService};
use crate::domain::value_objects::Conventions;
use crate::infrastructure::external::notifications::NotificationServiceClient;
use crate::infrastructure::filesystem::workspace::WorkspaceService;
use crate::shared::config::SystemConfig;
use crate::shared::constants::{OperationType, ReportType, SessionStatus};
use crate::shared::error::{AppError, AppResult, ErrorKind};
use crate::shared::pyfmt;

async fn with_save<F: Future<Output = AppResult<()>>>(body: F, session: &SessionService, query: &str) -> AppResult<()> {
    let outcome = body.await;
    let saved = session.save(query).await;
    match saved {
        Err(e) => Err(e),
        Ok(()) => outcome,
    }
}

/// The session's internal history right now.
fn history(ctx: &SharedSession) -> History {
    ctx.history()
}

// --- generate ------------------------------------------------------------------------------

pub struct TerraformCrudHandler {
    pub ctx: SharedSession,
    pub session: SessionService,
    pub terraform: Arc<dyn Terraform>,
    pub validation: TerraformValidationService,
    pub templates: TemplateOrchestrationService,
    pub requests_filter: RequestsFilterService,
    pub report: ReportService,
    pub targets: TerraformTargetService,
    pub drift: TerraformDriftService,
    pub compliance: ComplianceCheckService,
    pub workspace: WorkspaceService,
    pub db: DatabaseService,
    pub notifications: NotificationServiceClient,
    pub cfg: &'static SystemConfig,
}

impl TerraformCrudHandler {
    pub async fn handle(&self, q: &str) -> AppResult<()> {
        with_save(self.round(q), &self.session, q).await
    }

    async fn round(&self, q: &str) -> AppResult<()> {
        let ctx = &self.ctx;
        self.session.next_round(q).await?;
        self.session
            .update_status_with_llm(q, SessionStatus::Filtering, &history(ctx))
            .await?;
        let operation = ctx.read(|c| c.operation);
        self.requests_filter.filter(q, ctx, operation).await?;

        let conventions = self.templates.compose_template(q, &history(ctx)).await?;

        let terraform = self.terraform.clone();
        let targets = self.targets.clone();
        let plan_callback = move |local_history: History| {
            let terraform = terraform.clone();
            let targets = targets.clone();
            async move {
                let t = targets.generate_session(&local_history, None).await?;
                Ok(ValidationResult::Plan(terraform.plan(&t).await?))
            }
            .boxed()
        };
        let plan_result = self
            .validation
            .generate_and_validate(
                q,
                ctx,
                LoopSpec {
                    conventions: &conventions,
                    include_forbidden_actions: true,
                    operation_type: OperationType::Generate,
                    max_iterations: self.cfg.orchestration.max_validation_iteration,
                },
                &plan_callback,
                None,
            )
            .await?;
        let ValidationResult::Plan(plan_result) = plan_result else {
            return Err(AppError::internal("generate validation returned a non-plan result"));
        };
        if !plan_result.ok {
            let fail_msg = self
                .report
                .summarize_problem(&plan_result.feedback, &history(ctx))
                .await?;
            return Err(AppError::kind(ErrorKind::TerraformValidationFailed, fail_msg, 500));
        }

        let drift = self
            .drift
            .detect_and_resolve_drift(plan_result.plan.clone(), true, &plan_result.targets, &conventions, 2)
            .await?;

        let report_value = self
            .report
            .generate_report(ctx, ReportType::Generate, &drift.stdout)
            .await?;
        let report: TerraformPlanReport =
            serde_json::from_value(report_value).map_err(|e| AppError::internal(e.to_string()))?;

        let check = self.compliance.check(ctx, &conventions, &drift.stdout).await?;

        let high_impact = self.cfg.orchestration.block_on_high_impact && report.potential_impact.banner.level == "high";

        let id = ctx.id();
        if !self.db.set_lock(&id, !check.passed || high_impact).await? {
            return Err(AppError::kind(
                ErrorKind::SetLock,
                "Error updating DB session lock.",
                500,
            ));
        }
        let owner = ctx.read(|c| c.user_id.clone());
        if !check.passed {
            self.notifications
                .notify_compliance_failure(&id, &owner, &check.summary)
                .await;
        }
        if high_impact {
            self.notifications
                .notify_high_impact(&id, &owner, &report.potential_impact.banner.description)
                .await;
        }
        let call_dir = ctx.read(|c| c.call_dir());
        self.workspace.pin_workspace(&id, &call_dir)?;
        Ok(())
    }
}

// --- drift ----------------------------------------------------------------------------------

pub struct TerraformDriftHandler {
    pub ctx: SharedSession,
    pub session: SessionService,
    pub templates: TemplateOrchestrationService,
    pub requests_filter: RequestsFilterService,
    pub report: ReportService,
    pub targets: TerraformTargetService,
    pub drift: TerraformDriftService,
    pub cfg: &'static SystemConfig,
}

impl TerraformDriftHandler {
    pub async fn handle(&self, q: &str, is_partial: bool) -> AppResult<()> {
        with_save(self.round(q, is_partial), &self.session, q).await
    }

    async fn round(&self, q: &str, is_partial: bool) -> AppResult<()> {
        let ctx = &self.ctx;
        self.session.next_round(q).await?;
        self.session
            .update_status_with_llm(q, SessionStatus::Filtering, &history(ctx))
            .await?;
        let mut targets: Vec<String> = Vec::new();
        if is_partial {
            let operation = ctx.read(|c| c.operation);
            self.requests_filter.filter(q, ctx, operation).await?;
        }
        let conventions = self.templates.compose_template(q, &history(ctx)).await?;
        if is_partial {
            targets = self.targets.generate_drift(q, &history(ctx), &conventions).await?;
        }
        let drift = self
            .drift
            .detect_and_resolve_drift(
                None,
                false,
                &targets,
                &conventions,
                self.cfg.orchestration.max_drift_reports,
            )
            .await?;
        let mut content = String::from(
            "The drift remediation round has finished. Report the reconciliation from the changes on the session branch.",
        );
        if !drift.in_sync {
            let shown = if drift.feedback.is_empty() {
                &drift.drift
            } else {
                &drift.feedback
            };
            content.push_str(&format!(
                "\n\nUnreconciled drift. Please note, the plan still shows this drift: {shown}"
            ));
        }
        if !drift.excluded.is_empty() {
            content.push_str(&format!(
                "\n\nWhitelisted exceptions. Please note, this drift was left unreconciled on purpose, covered by the drift exception rules:\n{}",
                drift.excluded.join("\n")
            ));
        }
        self.report.generate_report(ctx, ReportType::Drift, &content).await?;
        Ok(())
    }
}

// --- apply ------------------------------------------------------------------------------------

/// Apply the session's pinned plan — nothing more. The plan was validated
/// and reviewed by the round that pinned its workspace; only a new
/// generate/drift round can produce the next appliable plan.
pub struct TerraformApplyHandler {
    pub ctx: SharedSession,
    pub terraform: Arc<dyn Terraform>,
    pub session: SessionService,
    pub report: ReportService,
    pub templates: TemplateOrchestrationService,
    pub compliance: ComplianceCheckService,
    pub workspace: WorkspaceService,
    pub notifications: NotificationServiceClient,
}

impl TerraformApplyHandler {
    pub async fn handle(&self) -> AppResult<()> {
        let round_query = "Terraform apply.";
        let outcome = self.round(round_query).await;
        self.workspace.discard_pinned(&self.ctx.id());
        match self.session.save(round_query).await {
            Err(e) => Err(e),
            Ok(()) => outcome,
        }
    }

    async fn round(&self, round_query: &str) -> AppResult<()> {
        let ctx = &self.ctx;
        let q = "Apply the IaC session changes";
        self.session.next_round(round_query).await?;
        self.session
            .update_status_with_llm(q, SessionStatus::Apply, &history(ctx))
            .await?;
        let id = ctx.id();
        if self.workspace.pinned_plan_path(&id).is_none() {
            return Err(AppError::kind(
                ErrorKind::TerraformValidationFailed,
                "No reviewed plan is pinned for this session; run a generate or drift round before applying.",
                409,
            ));
        }
        let apply_result = self.terraform.apply().await?;
        let report_value = self
            .report
            .generate_report(
                ctx,
                ReportType::Apply,
                &format!("{}{}", apply_result.stdout, apply_result.feedback),
            )
            .await?;
        let report: TerraformApplyReport =
            serde_json::from_value(report_value).map_err(|e| AppError::internal(e.to_string()))?;
        ctx.append_history(q, report.execution_summary.clone());
        if !apply_result.ok {
            let owner = ctx.read(|c| c.user_id.clone());
            self.notifications
                .notify_apply_failure(&id, &owner, &report.execution_summary)
                .await;
        }
        let _ = (&self.templates, &self.compliance);
        Ok(())
    }
}

// --- import ------------------------------------------------------------------------------------

pub struct TerraformImportHandler {
    pub ctx: SharedSession,
    pub session: SessionService,
    pub terraform: Arc<dyn Terraform>,
    pub validation: TerraformValidationService,
    pub templates: TemplateOrchestrationService,
    pub requests_filter: RequestsFilterService,
    pub import: TerraformImportService,
    pub import_address: TerraformImportAddressService,
    pub targets: TerraformTargetService,
    pub drift: TerraformDriftService,
    pub report: ReportService,
    pub task: TaskService,
    pub cfg: &'static SystemConfig,
}

impl TerraformImportHandler {
    pub async fn handle(&self, q: &str, is_partial: bool) -> AppResult<()> {
        with_save(self.round(q, is_partial), &self.session, q).await
    }

    /// Close a round that found nothing to import with an empty report:
    /// the session completes, with `msg` saying which dead end was reached.
    async fn report_nothing_to_import(&self, q: &str, msg: &str, excluded: &[String]) -> AppResult<()> {
        self.ctx.append_history(q, msg);
        let content = pyfmt::json_dumps(&json!({
            "selected_resource_ids": [],
            "excluded_resource_ids": excluded,
            "import_results": {"imported": [], "failed": []},
            "summary": msg,
        }));
        self.report
            .generate_report(&self.ctx, ReportType::Import, &content)
            .await?;
        Ok(())
    }

    async fn round(&self, q: &str, is_partial: bool) -> AppResult<()> {
        let ctx = &self.ctx;
        self.session.next_round(q).await?;
        self.session
            .update_status_with_llm(q, SessionStatus::Filtering, &history(ctx))
            .await?;
        if is_partial {
            let operation = ctx.read(|c| c.operation);
            self.requests_filter.filter(q, ctx, operation).await?;
        }
        let conventions = self.templates.compose_template(q, &history(ctx)).await?;

        let (scope_id, provider) = ctx.read(|c| (c.scope_id.clone(), c.terraform_prv));
        let discovery = self.import.get_unmanaged_resources(&scope_id, provider).await?;
        let mut unmanaged_ids = discovery.resource_ids.clone();
        if unmanaged_ids.is_empty() {
            return self
                .report_nothing_to_import(q, &discovery.feedback, &discovery.excluded)
                .await;
        }
        if is_partial {
            let filtered = self
                .task
                .filter_imports(q, &unmanaged_ids, &conventions, &history(ctx))
                .await?;
            unmanaged_ids = filtered.selected;
            if unmanaged_ids.is_empty() {
                let msg = if filtered.explanation.is_empty() {
                    "No unmanaged resource matched the request.".to_string()
                } else {
                    filtered.explanation
                };
                return self.report_nothing_to_import(q, &msg, &discovery.excluded).await;
            }
        }

        let terraform = self.terraform.clone();
        let targets = self.targets.clone();
        let plan_callback = move |local_history: History| {
            let terraform = terraform.clone();
            let targets = targets.clone();
            async move {
                let t = targets.generate_session(&local_history, None).await?;
                Ok(ValidationResult::Plan(terraform.plan(&t).await?))
            }
            .boxed()
        };
        let request = format!(
            "Create a Terraform resource block for each of these {}",
            unmanaged_ids
                .iter()
                .map(|r| format!("- {r}"))
                .collect::<Vec<_>>()
                .join("\n")
        );
        let empty = Conventions::empty();
        let plan_result = self
            .validation
            .generate_and_validate(
                &request,
                ctx,
                LoopSpec {
                    conventions: &empty,
                    include_forbidden_actions: false,
                    operation_type: OperationType::Import,
                    max_iterations: self.cfg.orchestration.max_import_iteration,
                },
                &plan_callback,
                None,
            )
            .await?;
        let import_targets = plan_result.targets();
        let mut plan_after_import = plan_result.stdout();

        let state: Arc<Mutex<(AttemptSet, AttemptSet)>> = Arc::new(Mutex::new((AttemptSet::new(), AttemptSet::new())));
        let import_callback = {
            let state = state.clone();
            let addresses = self.import_address.clone();
            let importer = self.import.clone();
            let ids = unmanaged_ids.clone();
            move |_history: History| {
                let state = state.clone();
                let addresses = addresses.clone();
                let importer = importer.clone();
                let ids = ids.clone();
                async move {
                    let failed_now = state.lock().expect("import state").1.clone();
                    let mut cmds = if failed_now.is_empty() {
                        addresses.get_import_addresses(ImportTargets::Ids(&ids)).await?
                    } else {
                        addresses
                            .get_import_addresses(ImportTargets::Attempts(&failed_now))
                            .await?
                    };
                    let imported_now = state.lock().expect("import state").0.clone();
                    cmds.difference_update(&imported_now);
                    let outcome = importer.import_resources(&cmds).await?;
                    let mut guard = state.lock().expect("import state");
                    let (imported, failed) = &mut *guard;
                    imported.update(&outcome.imported);
                    failed.difference_update(&outcome.failed);
                    failed.update(&outcome.failed);
                    failed.difference_update(imported);
                    tracing::debug!(
                        "import_cmds: {}\nimported: {}\nfailed: {}\n",
                        pyfmt::repr_str_list(&cmds.iter().map(|r| r.address.clone()).collect::<Vec<_>>()),
                        pyfmt::repr_str_list(&imported.iter().map(|r| r.address.clone()).collect::<Vec<_>>()),
                        pyfmt::repr_str_list(&failed.iter().map(|r| r.address.clone()).collect::<Vec<_>>()),
                    );
                    Ok(ValidationResult::Import(TerraformImportDto {
                        imported: imported.clone(),
                        failed: failed.clone(),
                    }))
                }
                .boxed()
            }
        };
        let task = self.task.clone();
        let split_errors = move |errors: String| {
            let task = task.clone();
            async move { task.split_errors(&errors, OperationType::Import).await }.boxed()
        };

        let mut import_results = import_callback(history(ctx)).await?;
        if !import_results.ok() {
            let q2 = split_errors(import_results.feedback()).await?;
            match self
                .validation
                .generate_and_validate(
                    &q2,
                    ctx,
                    LoopSpec {
                        conventions: &empty,
                        include_forbidden_actions: false,
                        operation_type: OperationType::Generate,
                        max_iterations: self.cfg.orchestration.max_import_iteration,
                    },
                    &import_callback,
                    Some(&split_errors),
                )
                .await
            {
                Ok(r) => import_results = r,
                Err(e) if e.is(ErrorKind::ValidationLoopExceeded) => match e.result.as_deref() {
                    Some(r @ ValidationResult::Import(_)) => import_results = r.clone(),
                    _ => return Err(e),
                },
                Err(e) => return Err(e),
            }
        }

        if !import_results.stdout().is_empty() {
            let drift = self
                .drift
                .detect_and_resolve_drift(
                    None,
                    false,
                    &import_targets,
                    &conventions,
                    self.cfg.orchestration.max_drift_reports,
                )
                .await?;
            if !drift.feedback.is_empty() {
                let fail_msg = self.report.summarize_problem(&drift.feedback, &history(ctx)).await?;
                return Err(AppError::kind(ErrorKind::TerraformValidationFailed, fail_msg, 500));
            }
            plan_after_import = drift.stdout;
        }

        let (imported, failed) = state.lock().expect("import state").clone();
        let content = pyfmt::json_dumps(&json!({
            "selected_resource_ids": unmanaged_ids,
            "excluded_resource_ids": discovery.excluded,
            "import_results": {
                "imported": imported.iter().map(|a| a.as_dict()).collect::<Vec<Value>>(),
                "failed": failed.iter().map(|a| a.as_dict()).collect::<Vec<Value>>(),
            },
            "plan_after_import": plan_after_import,
        }));
        self.report.generate_report(ctx, ReportType::Import, &content).await?;
        Ok(())
    }
}
