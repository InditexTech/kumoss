// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

//! Prompt rendering and the prompt compositor chain.

use std::collections::HashSet;

use serde_json::Value;

use crate::domain::dto::{PromptTemplate, TerraformImportAttempt};
use crate::domain::entities::History;
use crate::domain::services::llm::LlmOrchestrationService;
use crate::domain::services::tools::ToolOrchestrationService;
use crate::domain::value_objects::Conventions;
use crate::infrastructure::templates::adapter::{SelectedIds, TemplateAdapter};
use crate::shared::constants::{OperationType, PromptsLibrary, ReportType, TargetGenerationMode, ToolContext};
use crate::shared::error::{AppError, AppResult};

/// One prompt and the arguments its layout takes.
pub enum Render<'a> {
    RequestsFilter {
        operation_type: OperationType,
    },
    TaskSplitter {
        operation_type: OperationType,
    },
    FilterReconciliation,
    FilterDriftExceptions,
    PromptCompositor {
        templates: Option<&'a [String]>,
        abbreviations: Option<&'a [String]>,
    },
    IacGenerator {
        operation_type: OperationType,
        resources: &'a [String],
        abbreviations: &'a [String],
        include_forbidden_actions: bool,
    },
    ImportFilter {
        unmanaged_ids: &'a [String],
        resources: &'a [String],
        abbreviations: &'a [String],
    },
    ImportExceptions,
    ImportAddresses {
        selected: SelectedIds<'a>,
    },
    TargetGenerator {
        mode: TargetGenerationMode,
        resources: Option<&'a [String]>,
    },
    ReportGenerator {
        report_type: ReportType,
    },
    PrGenerator {
        operation_type: OperationType,
    },
    ComplianceChecker {
        resources: &'a [String],
        abbreviations: &'a [String],
    },
    StatusUpdate,
    ChatReply,
}

/// The ids an import-address round maps, owned.
pub enum ImportSelection {
    Ids(Vec<String>),
    Attempts(Vec<TerraformImportAttempt>),
}

#[derive(Clone)]
pub struct TemplateOrchestrationService {
    templates: TemplateAdapter,
    llm: LlmOrchestrationService,
    tools: ToolOrchestrationService,
}

impl TemplateOrchestrationService {
    pub fn new(templates: TemplateAdapter, llm: LlmOrchestrationService, tools: ToolOrchestrationService) -> Self {
        Self { templates, llm, tools }
    }

    pub fn adapter(&self) -> &TemplateAdapter {
        &self.templates
    }

    pub async fn render(&self, request: Render<'_>) -> AppResult<PromptTemplate> {
        let t = &self.templates;
        let (kind, prompt) = match request {
            Render::RequestsFilter { operation_type } => (
                PromptsLibrary::RequestsFilter,
                t.render_requests_filter(operation_type).await?,
            ),
            Render::TaskSplitter { operation_type } => {
                (PromptsLibrary::TaskSplitter, t.render_task_splitter(operation_type)?)
            }
            Render::FilterReconciliation => (PromptsLibrary::FilterReconciliation, t.render_filter_reconciliation()?),
            Render::FilterDriftExceptions => (
                PromptsLibrary::FilterDriftExceptions,
                t.render_filter_drift_exceptions().await?,
            ),
            Render::PromptCompositor {
                templates,
                abbreviations,
            } => (
                PromptsLibrary::PromptCompositor,
                t.render_prompt_compositor(templates, abbreviations).await?,
            ),
            Render::IacGenerator {
                operation_type,
                resources,
                abbreviations,
                include_forbidden_actions,
            } => (
                PromptsLibrary::IacGenerator,
                t.render_iac_generator(operation_type, resources, abbreviations, include_forbidden_actions)
                    .await?,
            ),
            Render::ImportFilter {
                unmanaged_ids,
                resources,
                abbreviations,
            } => (
                PromptsLibrary::ImportFilter,
                t.render_import_filter(unmanaged_ids, resources, abbreviations).await?,
            ),
            Render::ImportExceptions => (PromptsLibrary::ImportExceptions, t.render_import_exceptions().await?),
            Render::ImportAddresses { selected } => {
                (PromptsLibrary::ImportAddresses, t.render_import_addresses(&selected)?)
            }
            Render::TargetGenerator { mode, resources } => (
                PromptsLibrary::TargetGenerator,
                t.render_target_generator(mode, resources).await?,
            ),
            Render::ReportGenerator { report_type } => (
                PromptsLibrary::ReportGenerator,
                t.render_report_generator(report_type).await?,
            ),
            Render::PrGenerator { operation_type } => {
                (PromptsLibrary::PrGenerator, t.render_pr_generator(operation_type)?)
            }
            Render::ComplianceChecker {
                resources,
                abbreviations,
            } => (
                PromptsLibrary::ComplianceChecker,
                t.render_compliance_checker(resources, abbreviations).await?,
            ),
            Render::StatusUpdate => (PromptsLibrary::StatusUpdate, t.render_status_update()?),
            Render::ChatReply => (PromptsLibrary::ChatReply, t.render_chat_reply()?),
        };
        Ok(PromptTemplate { kind, prompt })
    }

    /// Two-pass prompt compositor: infer templates and abbreviations from
    /// the query, then re-run with those already selected to discover
    /// related ones, and merge both passes without duplicates.
    pub async fn compose_template(&self, query: &str, history: &History) -> AppResult<Conventions> {
        let compositor_tools = self.tools.get_available_tools(&[ToolContext::PromptCompositor])?;
        let first = self
            .llm
            .generate(
                query,
                compositor_tools,
                None,
                &self
                    .render(Render::PromptCompositor {
                        templates: None,
                        abbreviations: None,
                    })
                    .await?,
                Some(history),
            )
            .await?;
        let templates = string_list(first.require("templates")?)?;
        let abbreviations = string_list(first.require("abbreviations")?)?;

        let second = self
            .llm
            .generate(
                query,
                self.tools.get_available_tools(&[ToolContext::PromptCompositor])?,
                None,
                &self
                    .render(Render::PromptCompositor {
                        templates: Some(&templates),
                        abbreviations: Some(&abbreviations),
                    })
                    .await?,
                Some(history),
            )
            .await?;
        let related_templates = string_list(second.require("templates")?)?;
        let related_abbreviations = string_list(second.require("abbreviations")?)?;

        let merged_templates = dedupe(templates.into_iter().chain(related_templates));
        let merged_abbreviations = dedupe(abbreviations.into_iter().chain(related_abbreviations));
        tracing::debug!(
            "Prompt compositor merged templates: {} ",
            crate::shared::pyfmt::repr_str_list(&merged_templates)
        );
        tracing::debug!(
            "Prompt compositor merged abbreviations: {} ",
            crate::shared::pyfmt::repr_str_list(&merged_abbreviations)
        );
        Ok(Conventions {
            templates: merged_templates,
            abbreviations: merged_abbreviations,
        })
    }
}

/// `list(set(a + b))`: the order of a Python set of strings is arbitrary,
/// first occurrence order is kept here.
fn dedupe(items: impl Iterator<Item = String>) -> Vec<String> {
    let mut seen = HashSet::new();
    items.filter(|i| seen.insert(i.clone())).collect()
}

/// A tool argument that must be a list of strings.
pub fn string_list(v: &Value) -> AppResult<Vec<String>> {
    match v {
        Value::Array(items) => Ok(items.iter().map(crate::shared::pyfmt::str_value).collect()),
        other => Err(AppError::internal(format!(
            "can only concatenate list (not \"{}\") to list",
            match other {
                Value::Null => "NoneType",
                Value::Bool(_) => "bool",
                Value::Number(_) => "int",
                Value::String(_) => "str",
                Value::Object(_) => "dict",
                Value::Array(_) => "list",
            }
        ))),
    }
}
