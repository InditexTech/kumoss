// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

//! Splits a task into simpler self-contained operations ("create a storage
//! account and a redis cache" → two operations), and filters operation
//! lists against the session's own changes and the exception rules.

use std::collections::HashMap;

use serde_json::{Value, json};

use crate::domain::dto::{FilteredImports, FilteredOperations, ReconciliationReport};
use crate::domain::entities::History;
use crate::domain::services::llm::LlmOrchestrationService;
use crate::domain::services::template::{Render, TemplateOrchestrationService};
use crate::domain::services::tools::ToolOrchestrationService;
use crate::domain::value_objects::Conventions;
use crate::shared::config::SystemConfig;
use crate::shared::constants::{OperationType, ToolContext};
use crate::shared::error::{AppError, AppResult};
use crate::shared::pyfmt;

fn strings(v: &Value) -> AppResult<Vec<String>> {
    match v {
        Value::Array(items) => Ok(items.iter().map(pyfmt::str_value).collect()),
        other => Err(AppError::internal(format!(
            "expected a list of operations, got {}",
            pyfmt::repr_value(other)
        ))),
    }
}

#[derive(Clone)]
pub struct TaskService {
    llm: LlmOrchestrationService,
    templates: TemplateOrchestrationService,
    tools: ToolOrchestrationService,
    cfg: &'static SystemConfig,
}

impl TaskService {
    pub fn new(
        llm: LlmOrchestrationService,
        templates: TemplateOrchestrationService,
        tools: ToolOrchestrationService,
        cfg: &'static SystemConfig,
    ) -> Self {
        Self {
            llm,
            templates,
            tools,
            cfg,
        }
    }

    pub async fn split_task(&self, task: &str, operation_type: OperationType) -> AppResult<Vec<Vec<String>>> {
        let response = self
            .llm
            .generate(
                task,
                self.tools
                    .get_available_tools(&[ToolContext::WorkspaceInspection, ToolContext::ExternalInformation])?,
                Some(self.tools.get_sentinel_tool(ToolContext::TaskSplitter)?),
                &self.templates.render(Render::TaskSplitter { operation_type }).await?,
                None,
            )
            .await?;
        Ok(self.group(strings(response.require("operations")?)?))
    }

    /// Turn a failed validation's errors into the next generation query:
    /// the operations lead, in the splitter's order, and the raw errors are
    /// dropped only when the split is non-empty.
    pub async fn split_errors(&self, errors: &str, operation_type: OperationType) -> AppResult<String> {
        let operations: Vec<String> = self
            .split_task(errors, operation_type)
            .await?
            .into_iter()
            .flatten()
            .collect();
        if operations.is_empty() {
            return Ok(errors.to_string());
        }
        let steps = operations
            .iter()
            .enumerate()
            .map(|(i, op)| format!("{}. {op}", i + 1))
            .collect::<Vec<_>>()
            .join("\n");
        Ok(format!("Fix the following errors:\n{steps}\n\n"))
    }

    /// Take the session's own changes out of the drift operations. Each
    /// operation comes back as a verdict itemising its changes, so one that
    /// bundles a session change with genuine drift is trimmed to the drift.
    /// An operation without a verdict is dropped: a missed remediation stays
    /// visible as remaining drift, while a reverted session change would
    /// silently undo the session's work.
    pub async fn filter_reconciliation(&self, operations: &[Vec<String>]) -> AppResult<Vec<Vec<String>>> {
        let flat: Vec<String> = operations.iter().flatten().cloned().collect();
        if flat.is_empty() {
            return Ok(Vec::new());
        }
        let query = pyfmt::json_dumps(&Value::Array(
            flat.iter()
                .enumerate()
                .map(|(i, op)| json!({"index": i + 1, "operation": op}))
                .collect(),
        ));
        let response = self
            .llm
            .generate(
                &query,
                self.tools.get_available_tools(&[ToolContext::WorkspaceInspection])?,
                Some(self.tools.get_sentinel_tool(ToolContext::FilterReconciliation)?),
                &self.templates.render(Render::FilterReconciliation).await?,
                None,
            )
            .await?;
        let report: ReconciliationReport =
            serde_json::from_value(response.result.clone()).map_err(|e| AppError::internal(e.to_string()))?;
        let verdicts: HashMap<i64, _> = report.verdicts.into_iter().map(|v| (v.index, v)).collect();
        let mut kept = Vec::new();
        for (i, op) in flat.iter().enumerate() {
            let index = (i + 1) as i64;
            let Some(verdict) = verdicts.get(&index) else {
                tracing::warn!("Reconciliation filter returned no verdict for operation {index}, dropping it: {op}");
                continue;
            };
            let removed = verdict.removed();
            if !removed.is_empty() {
                let text = removed
                    .iter()
                    .map(|c| format!("{} ({})", c.description, c.reason))
                    .collect::<Vec<_>>()
                    .join("; ");
                tracing::warn!("Reconciliation filter removed session changes from operation {index}: {text}");
            }
            if let Some(r) = verdict.reconciled(op) {
                kept.push(r);
            }
        }
        Ok(self.group(kept))
    }

    pub async fn filter_exceptions(&self, operations: &[Vec<String>]) -> AppResult<FilteredOperations> {
        let flat: Vec<String> = operations.iter().flatten().cloned().collect();
        if flat.is_empty() {
            return Ok(FilteredOperations {
                kept: Vec::new(),
                excluded: Vec::new(),
                explanation: String::new(),
            });
        }
        let query = pyfmt::json_dumps(&json!(flat));
        let response = self
            .llm
            .generate(
                &query,
                vec![self.tools.get_sentinel_tool(ToolContext::TaskSplitter)?],
                None,
                &self.templates.render(Render::FilterDriftExceptions).await?,
                None,
            )
            .await?;
        let kept = strings(response.require("operations")?)?;
        Ok(FilteredOperations {
            excluded: flat.iter().filter(|op| !kept.contains(op)).cloned().collect(),
            kept: self.group(kept),
            explanation: response.get("explanation").map(pyfmt::str_value).unwrap_or_default(),
        })
    }

    /// Narrow a scope's unmanaged resources to the ones a request asks for.
    /// The conventions travel with the query: the request is phrased in the
    /// repository's vocabulary, the resource ids carry none of it.
    pub async fn filter_imports(
        &self,
        query: &str,
        unmanaged_ids: &[String],
        conventions: &Conventions,
        history: &History,
    ) -> AppResult<FilteredImports> {
        if unmanaged_ids.is_empty() {
            return Ok(FilteredImports {
                selected: Vec::new(),
                explanation: String::new(),
            });
        }
        let response = self
            .llm
            .generate(
                query,
                vec![self.tools.get_sentinel_tool(ToolContext::TaskSplitter)?],
                None,
                &self
                    .templates
                    .render(Render::ImportFilter {
                        unmanaged_ids,
                        resources: &conventions.templates,
                        abbreviations: &conventions.abbreviations,
                    })
                    .await?,
                Some(history),
            )
            .await?;
        Ok(FilteredImports {
            selected: strings(response.require("operations")?)?,
            explanation: response.get("explanation").map(pyfmt::str_value).unwrap_or_default(),
        })
    }

    fn group(&self, ops: Vec<String>) -> Vec<Vec<String>> {
        let size = usize::try_from(self.cfg.orchestration.drift_group_operations)
            .unwrap_or(1)
            .max(1);
        ops.chunks(size).map(<[String]>::to_vec).collect()
    }
}
