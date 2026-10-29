// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

//! Terraform `-target` generation, and the import-address mapping.

use crate::domain::dto::{AttemptSet, TerraformImportAttempt};
use crate::domain::entities::History;
use crate::domain::services::llm::LlmOrchestrationService;
use crate::domain::services::template::{Render, TemplateOrchestrationService, string_list};
use crate::domain::services::tools::ToolOrchestrationService;
use crate::domain::value_objects::Conventions;
use crate::infrastructure::templates::adapter::SelectedIds;
use crate::shared::constants::{TargetGenerationMode, ToolContext};
use crate::shared::error::{AppError, AppResult};
use crate::shared::pyfmt;

#[derive(Clone)]
pub struct TerraformTargetService {
    tools: ToolOrchestrationService,
    llm: LlmOrchestrationService,
    templates: TemplateOrchestrationService,
}

impl TerraformTargetService {
    pub fn new(
        tools: ToolOrchestrationService,
        llm: LlmOrchestrationService,
        templates: TemplateOrchestrationService,
    ) -> Self {
        Self { tools, llm, templates }
    }

    pub async fn generate_session(&self, history: &History, query: Option<&str>) -> AppResult<Vec<String>> {
        let response = self
            .llm
            .generate(
                query
                    .filter(|q| !q.is_empty())
                    .unwrap_or("Generate the relevant Terraform targets."),
                self.tools.get_available_tools(&[ToolContext::WorkspaceInspection])?,
                Some(self.tools.get_sentinel_tool(ToolContext::TargetGenerator)?),
                &self
                    .templates
                    .render(Render::TargetGenerator {
                        mode: TargetGenerationMode::Session,
                        resources: None,
                    })
                    .await?,
                Some(history),
            )
            .await?;
        string_list(response.require("targets")?)
    }

    pub async fn generate_drift(
        &self,
        query: &str,
        history: &History,
        conventions: &Conventions,
    ) -> AppResult<Vec<String>> {
        let response = self
            .llm
            .generate(
                query,
                self.tools.get_available_tools(&[ToolContext::WorkspaceInspection])?,
                Some(self.tools.get_sentinel_tool(ToolContext::TargetGenerator)?),
                &self
                    .templates
                    .render(Render::TargetGenerator {
                        mode: TargetGenerationMode::Drift,
                        resources: Some(&conventions.templates),
                    })
                    .await?,
                Some(history),
            )
            .await?;
        string_list(response.require("targets")?)
    }
}

/// Resolves which resource blocks an import round generated and pairs each
/// Terraform address with the cloud resource id it must be imported from.
/// The external information tools ride along: the registry's import
/// example is what settles the id spelling the provider parses.
#[derive(Clone)]
pub struct TerraformImportAddressService {
    tools: ToolOrchestrationService,
    llm: LlmOrchestrationService,
    templates: TemplateOrchestrationService,
}

/// What an import-address round maps: the unmanaged ids on the first pass,
/// the failed attempts on a retry.
pub enum ImportTargets<'a> {
    Ids(&'a [String]),
    Attempts(&'a AttemptSet),
}

impl TerraformImportAddressService {
    pub fn new(
        tools: ToolOrchestrationService,
        llm: LlmOrchestrationService,
        templates: TemplateOrchestrationService,
    ) -> Self {
        Self { tools, llm, templates }
    }

    pub async fn get_import_addresses(&self, selected: ImportTargets<'_>) -> AppResult<AttemptSet> {
        let selected = match selected {
            ImportTargets::Ids(ids) => SelectedIds::Ids(ids),
            ImportTargets::Attempts(set) => SelectedIds::Attempts(set.iter().cloned().collect()),
        };
        let response = self
            .llm
            .generate(
                "Map the generated Terraform blocks to their cloud resource ids.",
                self.tools
                    .get_available_tools(&[ToolContext::WorkspaceInspection, ToolContext::ExternalInformation])?,
                Some(self.tools.get_sentinel_tool(ToolContext::ImportAddresses)?),
                &self.templates.render(Render::ImportAddresses { selected }).await?,
                None,
            )
            .await?;
        let imports = response.require("imports")?;
        let entries = imports
            .as_array()
            .ok_or_else(|| AppError::internal("imports is not a list"))?;
        let mut out = AttemptSet::new();
        for entry in entries {
            let field = |k: &str| -> AppResult<String> {
                entry
                    .get(k)
                    .map(pyfmt::str_value)
                    .ok_or_else(|| AppError::missing_key(k))
            };
            out.add(TerraformImportAttempt {
                address: field("address")?,
                resource_id: field("resource_id")?,
                listed_id: field("listed_id")?,
                error: String::new(),
            });
        }
        Ok(out)
    }
}
