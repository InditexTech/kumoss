// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

//! Drift detection and remediation, and import discovery.

use std::sync::{Arc, LazyLock};

use futures::FutureExt;
use indexmap::IndexMap;
use regex::Regex;

use crate::domain::dto::{
    AttemptSet, TerraformDiscoveryDto, TerraformDriftDto, TerraformImportAttempt, TerraformImportDto, ValidationResult,
};
use crate::domain::entities::{History, SharedSession};
use crate::domain::ports::Terraform;
use crate::domain::services::artifact_storage::ArtifactStorageService;
use crate::domain::services::session::SessionService;
use crate::domain::services::task::TaskService;
use crate::domain::services::template::{Render, TemplateOrchestrationService};
use crate::domain::services::validation::{LoopSpec, TerraformValidationService};
use crate::domain::value_objects::{Conventions, PlanRef};
use crate::shared::config::SystemConfig;
use crate::shared::constants::{ContentType, OperationType, SessionStatus, TerraformProvider};
use crate::shared::error::{AppError, AppResult};
use crate::shared::pyfmt;

#[derive(Clone)]
pub struct TerraformDriftService {
    ctx: SharedSession,
    session: SessionService,
    validation: TerraformValidationService,
    terraform: Arc<dyn Terraform>,
    split: TaskService,
    artifacts: ArtifactStorageService,
    cfg: &'static SystemConfig,
}

fn plan_of(result: &ValidationResult) -> Option<PlanRef> {
    match result {
        ValidationResult::Plan(p) => p.plan.clone(),
        ValidationResult::Import(_) => None,
    }
}

impl TerraformDriftService {
    pub fn new(
        ctx: SharedSession,
        session: SessionService,
        validation: TerraformValidationService,
        terraform: Arc<dyn Terraform>,
        split: TaskService,
        artifacts: ArtifactStorageService,
        cfg: &'static SystemConfig,
    ) -> Self {
        Self {
            ctx,
            session,
            validation,
            terraform,
            split,
            artifacts,
            cfg,
        }
    }

    /// Read drift out of a plan and reconcile it, bounded by
    /// `max_iterations`. `plan` is the plan to start from: a generate round
    /// hands over the one it just validated (its pre-check costs no extra
    /// plan); a dedicated drift session passes `None`. Every reconciliation
    /// group re-plans, and the last of those is what the next iteration
    /// reads; an iteration whose split produced no operations leaves no ref,
    /// so the next one plans for itself and keeps reading live state.
    pub async fn detect_and_resolve_drift(
        &self,
        plan: Option<PlanRef>,
        filter_session_changes: bool,
        targets: &[String],
        conventions: &Conventions,
        max_iterations: i64,
    ) -> AppResult<TerraformDriftDto> {
        let mut plan = plan;
        let mut drift = TerraformDriftDto::empty();
        let mut exclusions: Vec<String> = Vec::new();
        let resolved = |mut d: TerraformDriftDto, exclusions: &Vec<String>| {
            d.excluded = exclusions.clone();
            d
        };
        let terraform = self.terraform.clone();
        let targets_owned = targets.to_vec();
        let plan_callback = move |_history: History| {
            let terraform = terraform.clone();
            let targets = targets_owned.clone();
            async move { Ok(ValidationResult::Plan(terraform.plan(&targets).await?)) }.boxed()
        };
        let split = self.split.clone();
        let split_errors = move |errors: String| {
            let split = split.clone();
            async move { split.split_errors(&errors, OperationType::Generate).await }.boxed()
        };
        let max_validation = self.cfg.orchestration.max_validation_iteration;

        for i in 0..max_iterations.max(0) {
            tracing::debug!("Drift report no: {}/{max_iterations}", i + 1);
            self.session
                .update_status(
                    "Assessing drift on the targeted infrastructure.",
                    SessionStatus::Reconciling,
                    None,
                    None,
                )
                .await?;

            if plan.is_none() {
                let mut plan_result = ValidationResult::Plan(self.terraform.plan(targets).await?);
                if plan_of(&plan_result).is_none() {
                    let q = split_errors(plan_result.feedback()).await?;
                    plan_result = self
                        .validation
                        .generate_and_validate(
                            &q,
                            &self.ctx,
                            LoopSpec {
                                conventions,
                                include_forbidden_actions: false,
                                operation_type: OperationType::Generate,
                                max_iterations: max_validation,
                            },
                            &plan_callback,
                            Some(&split_errors),
                        )
                        .await?;
                }
                plan = plan_of(&plan_result);
            }

            let current = plan
                .as_ref()
                .ok_or_else(|| AppError::internal("'NoneType' object has no attribute 'workspace'"))?;
            drift = self.terraform.drift(current).await?;

            if drift.feedback.is_empty() {
                self.store_drift(&drift, targets).await?;
            }
            if drift.in_sync {
                break;
            }
            if !drift.feedback.is_empty() {
                tracing::error!("Drift could not be read: {}", drift.feedback);
                return Ok(resolved(drift, &exclusions));
            }

            let mut operations = self.split.split_task(&drift.drift, OperationType::Drift).await?;
            if filter_session_changes {
                operations = self.split.filter_reconciliation(&operations).await?;
                if operations.is_empty() {
                    tracing::warn!("Drift pre-check completed, remaining drift corresponds to session changes");
                    return Ok(resolved(drift, &exclusions));
                }
            }

            let filtered = self.split.filter_exceptions(&operations).await?;
            if !filtered.excluded.is_empty() {
                let note = if filtered.explanation.is_empty() {
                    filtered.excluded.join("; ")
                } else {
                    filtered.explanation.clone()
                };
                tracing::warn!("Drift exception rules excluded operations: {note}");
                exclusions.push(note);
            }
            if !operations.is_empty() && filtered.kept.is_empty() {
                tracing::warn!(
                    "Drift remediation stopped, every operation is covered by the drift exception rules: {}",
                    pyfmt::repr_str_list(&exclusions)
                );
                return Ok(resolved(drift, &exclusions));
            }
            let operations = filtered.kept;

            plan = None;
            for (idx, group) in operations.iter().enumerate() {
                tracing::debug!(
                    "Operation {}/{}: {}",
                    idx + 1,
                    operations.len(),
                    pyfmt::repr_str_list(group)
                );
                let result = self
                    .validation
                    .generate_and_validate(
                        &pyfmt::repr_str_list(group),
                        &self.ctx,
                        LoopSpec {
                            conventions,
                            include_forbidden_actions: false,
                            operation_type: OperationType::Generate,
                            max_iterations: max_validation,
                        },
                        &plan_callback,
                        None,
                    )
                    .await?;
                plan = plan_of(&result);
            }
        }

        if let (Some(p), Some(dp)) = (&plan, &drift.plan)
            && p != dp
        {
            drift = self.terraform.drift(p).await?;
        }
        if drift.in_sync {
            tracing::warn!("Drift pre-check completed, resources are synchronized");
        } else {
            tracing::warn!("Drift resolution completed but issues remain: {}", drift.drift);
        }
        Ok(resolved(drift, &exclusions))
    }

    async fn store_drift(&self, drift: &TerraformDriftDto, targets: &[String]) -> AppResult<()> {
        let (kind, content) = if drift.drift.is_empty() {
            ("plan", drift.stdout.as_str())
        } else {
            ("drift", drift.drift.as_str())
        };
        let mut meta = IndexMap::new();
        meta.insert("type".to_string(), kind.to_string());
        self.artifacts
            .store_terraform_plan(
                &self.ctx.id(),
                self.ctx.round_id(),
                targets,
                content,
                ContentType::Text,
                meta,
            )
            .await?;
        Ok(())
    }
}

static BULLET: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"^\s*[-*]\s+(.+?)\s*$").unwrap());

#[derive(Clone)]
pub struct TerraformImportService {
    terraform: Arc<dyn Terraform>,
    templates: TemplateOrchestrationService,
}

impl TerraformImportService {
    pub fn new(terraform: Arc<dyn Terraform>, templates: TemplateOrchestrationService) -> Self {
        Self { terraform, templates }
    }

    /// Diff the cloud scope against the Terraform state: the unmanaged
    /// resource IDs, with the import exception list applied. Azure ARM IDs
    /// compare case-insensitively; every other provider compares exactly.
    pub async fn get_unmanaged_resources(
        &self,
        scope_id: &str,
        terraform_provider: TerraformProvider,
    ) -> AppResult<TerraformDiscoveryDto> {
        let state = self.terraform.state_resource_ids().await?;
        let managed = state.resource_ids;
        tracing::debug!(
            "Managed resources for scope {scope_id}: {}",
            pyfmt::repr_str_list(&managed)
        );
        let scope = self.terraform.scope_resource_ids(scope_id, terraform_provider).await?;
        tracing::debug!(
            "Scope resources for scope {scope_id}: {}",
            pyfmt::repr_str_list(&scope.resource_ids)
        );

        if !scope.feedback.is_empty() {
            tracing::warn!("Listing scope {scope_id} failed: {}", scope.feedback);
            return Ok(TerraformDiscoveryDto {
                resource_ids: Vec::new(),
                feedback: format!("The scope {scope_id} could not be listed: {}", scope.feedback),
                excluded: Vec::new(),
            });
        }
        if scope.resource_ids.is_empty() {
            return Ok(TerraformDiscoveryDto {
                resource_ids: Vec::new(),
                feedback: format!("The scope {scope_id} holds no importable resource."),
                excluded: Vec::new(),
            });
        }
        let key = |rid: &str| -> String {
            if terraform_provider == TerraformProvider::Azure {
                pyfmt::casefold(rid)
            } else {
                rid.to_string()
            }
        };
        let mut seen: std::collections::HashSet<String> = managed.iter().map(|r| key(r)).collect();
        let mut unmanaged: Vec<String> = Vec::new();
        for rid in &scope.resource_ids {
            if seen.insert(key(rid)) {
                unmanaged.push(rid.clone());
            }
        }
        unmanaged.sort();
        tracing::debug!(
            "Unmanaged resources for scope {scope_id}: {}",
            pyfmt::repr_str_list(&unmanaged)
        );
        if unmanaged.is_empty() {
            return Ok(TerraformDiscoveryDto {
                resource_ids: Vec::new(),
                feedback: format!("Every resource in the scope {scope_id} is already managed."),
                excluded: Vec::new(),
            });
        }
        let exceptions = self.templates.render(Render::ImportExceptions).await?;
        let withheld: std::collections::HashSet<String> =
            Self::exception_ids(&exceptions.prompt).iter().map(|r| key(r)).collect();
        let importable: Vec<String> = unmanaged
            .iter()
            .filter(|r| !withheld.contains(&key(r)))
            .cloned()
            .collect();
        let excluded: Vec<String> = unmanaged
            .iter()
            .filter(|r| withheld.contains(&key(r)))
            .cloned()
            .collect();
        if !excluded.is_empty() {
            tracing::debug!(
                "Import exceptions withheld for scope {scope_id}: {}",
                pyfmt::repr_str_list(&excluded)
            );
        }
        Ok(TerraformDiscoveryDto {
            feedback: if importable.is_empty() {
                format!("Every unmanaged resource in the scope {scope_id} is on the import exception list.")
            } else {
                String::new()
            },
            resource_ids: importable,
            excluded,
        })
    }

    /// The resource IDs an import exception list names: every markdown
    /// bullet is one ID, optionally in backticks; every other line is prose.
    pub fn exception_ids(body: &str) -> Vec<String> {
        let mut ids = Vec::new();
        for line in pyfmt::splitlines(body) {
            if let Some(c) = BULLET.captures(line) {
                let rid = pyfmt::strip(pyfmt::strip(&c[1]).trim_matches('`')).to_string();
                if !rid.is_empty() {
                    ids.push(rid);
                }
            }
        }
        ids
    }

    pub async fn import_resources(&self, imports: &AttemptSet) -> AppResult<TerraformImportDto> {
        let mut outcome = TerraformImportDto::empty();
        for r in imports.iter() {
            let result = self.terraform.import_resource(&r.address, &r.resource_id).await?;
            let attempt = TerraformImportAttempt {
                address: r.address.clone(),
                resource_id: r.resource_id.clone(),
                listed_id: r.listed_id.clone(),
                error: result.feedback.clone(),
            };
            if result.ok {
                outcome.imported.add(attempt);
            } else {
                tracing::warn!(
                    "Import failed for {} ({}): {}",
                    r.address,
                    r.resource_id,
                    result.feedback
                );
                outcome.failed.add(attempt);
            }
        }
        Ok(outcome)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn exception_list_parsing() {
        let body =
            "Resources never imported:\n- `/subscriptions/x/rg/a`\n* /subscriptions/x/rg/b  \nprose line\n  -   \n";
        assert_eq!(
            TerraformImportService::exception_ids(body),
            vec!["/subscriptions/x/rg/a".to_string(), "/subscriptions/x/rg/b".to_string()]
        );
    }
}
