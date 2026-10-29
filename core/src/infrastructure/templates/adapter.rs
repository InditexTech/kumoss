// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

//! Renders the system prompts: a Jinja layout per prompt, filled with the
//! provider guidelines and resource templates fetched from Phoenix.

use indexmap::IndexMap;
use minijinja::Value as JValue;
use serde_json::{Value, json};

use crate::domain::dto::TerraformImportAttempt;
use crate::infrastructure::templates::env::JINJA;
use crate::infrastructure::templates::fetcher::PromptFetcher;
use crate::shared::constants::{OperationType, ReportType, TargetGenerationMode, TerraformProvider};
use crate::shared::error::{AppError, AppResult};
use crate::shared::pyfmt::repr_str_list;

const CORE: &str = "base_layouts/core/";
const MESSAGE: &str = "base_layouts/messages/";

/// The ids an import-address round maps: the unmanaged ids on the first
/// pass, the failed attempts on a retry.
pub enum SelectedIds<'a> {
    Ids(&'a [String]),
    Attempts(Vec<TerraformImportAttempt>),
}

#[derive(Clone)]
pub struct TemplateAdapter {
    scope: String,
    cwd: String,
    environment: String,
    fetcher: PromptFetcher,
}

fn render(template: &str, ctx: Value) -> AppResult<String> {
    let t = JINJA
        .get_template(template)
        .map_err(|e| AppError::internal(format!("template {template}: {e}")))?;
    t.render(JValue::from_serialize(&ctx))
        .map_err(|e| AppError::internal(format!("template {template}: {e}")))
}

impl TemplateAdapter {
    pub fn new(template_provider: TerraformProvider, cwd: &str, environment: &str, fetcher: PromptFetcher) -> Self {
        Self {
            scope: template_provider.value().to_string(),
            cwd: cwd.to_string(),
            environment: environment.to_string(),
            fetcher,
        }
    }

    async fn fetch(&self, name: &str, scope: &str, kind: &str) -> AppResult<String> {
        self.fetcher.fetch(name, scope, kind, &self.environment).await
    }

    async fn fetch_guidelines(&self, name: &str) -> AppResult<String> {
        let scope = self.scope.clone();
        self.fetch(name, &scope, "guidelines").await
    }

    async fn resources_templates(&self, resources: &[String]) -> AppResult<Option<IndexMap<String, String>>> {
        if resources.is_empty() {
            return Ok(None);
        }
        let mut out = IndexMap::new();
        for r in resources {
            let content = self.fetch(r, &self.scope.clone(), "resources").await?;
            out.insert(r.clone(), content);
        }
        Ok(Some(out))
    }

    pub async fn render_target_generator(
        &self,
        mode: TargetGenerationMode,
        resources: Option<&[String]>,
    ) -> AppResult<String> {
        let template = format!("{CORE}target_{}_generator.jinja", mode.value());
        let mut ctx = serde_json::Map::new();
        if mode == TargetGenerationMode::Drift {
            let policies = self.fetch("targeting_policies", "general", "guidelines").await?;
            ctx.insert("RELEVANT_TEMPLATES".into(), json!(resources.unwrap_or(&[])));
            ctx.insert("TARGETING_POLICIES".into(), json!(policies));
            ctx.insert("CWD".into(), json!(self.cwd));
        }
        render(&template, Value::Object(ctx))
    }

    pub async fn render_report_generator(&self, report_type: ReportType) -> AppResult<String> {
        let mut ctx = serde_json::Map::new();
        ctx.insert("REPORT_TYPE".into(), json!(report_type.value()));
        if report_type == ReportType::Generate {
            ctx.insert(
                "IMPACT_ANALYSIS_RULES".into(),
                json!(self.fetch("impact", "general", "compliance").await?),
            );
        }
        render(&format!("{CORE}report_generator.jinja"), Value::Object(ctx))
    }

    pub fn render_pr_generator(&self, operation_type: OperationType) -> AppResult<String> {
        render(
            &format!("{CORE}pr_generator.jinja"),
            json!({"OPERATION_TYPE": operation_type.value()}),
        )
    }

    pub async fn render_requests_filter(&self, operation_type: OperationType) -> AppResult<String> {
        let requests_guidelines = self.fetch("requests", "general", "guidelines").await?;
        let forbidden_actions = self.fetch_guidelines("forbidden_actions").await?;
        render(
            &format!("{CORE}requests_filter.jinja"),
            json!({
                "CWD": self.cwd,
                "FORBIDDEN_ACTIONS": forbidden_actions,
                "REQUESTS_GUIDELINES": requests_guidelines,
                "OPERATION_TYPE": operation_type.value(),
            }),
        )
    }

    pub fn render_task_splitter(&self, operation_type: OperationType) -> AppResult<String> {
        render(
            &format!("{CORE}task_splitter.jinja"),
            json!({"IS_DRIFT": operation_type == OperationType::Drift}),
        )
    }

    pub fn render_filter_reconciliation(&self) -> AppResult<String> {
        render(&format!("{CORE}filter_reconciliation.jinja"), json!({"CWD": self.cwd}))
    }

    pub fn render_import_addresses(&self, selected_ids: &SelectedIds<'_>) -> AppResult<String> {
        let ids = match selected_ids {
            SelectedIds::Ids(ids) => json!(ids),
            SelectedIds::Attempts(attempts) => {
                Value::Array(attempts.iter().map(TerraformImportAttempt::as_dict).collect())
            }
        };
        render(
            &format!("{CORE}import_addresses.jinja"),
            json!({"CWD": self.cwd, "selected_ids": ids}),
        )
    }

    pub async fn render_filter_drift_exceptions(&self) -> AppResult<String> {
        let exceptions = self.fetch_guidelines("drift_exceptions").await?;
        render(
            &format!("{CORE}filter_drift_exceptions.jinja"),
            json!({"DRIFT_EXCEPTIONS": exceptions}),
        )
    }

    pub fn render_joker(&self) -> AppResult<String> {
        render(&format!("{MESSAGE}joker.jinja"), json!({}))
    }

    pub fn render_status_update(&self) -> AppResult<String> {
        render(&format!("{MESSAGE}status_update.jinja"), json!({}))
    }

    pub fn render_chat_reply(&self) -> AppResult<String> {
        render(&format!("{MESSAGE}chat_reply.jinja"), json!({}))
    }

    pub fn render_search_summarizer(&self, irrelevant_marker: &str) -> AppResult<String> {
        render(
            &format!("{MESSAGE}search_summarizer.jinja"),
            json!({"IRRELEVANT_MARKER": irrelevant_marker}),
        )
    }

    pub fn render_search_selector(&self) -> AppResult<String> {
        render(&format!("{MESSAGE}search_selector.jinja"), json!({}))
    }

    pub async fn render_import_filter(
        &self,
        unmanaged_ids: &[String],
        resources: &[String],
        abbreviations: &[String],
    ) -> AppResult<String> {
        let mut concrete: Vec<String> = if abbreviations.is_empty() {
            Vec::new()
        } else {
            vec![format!(
                "This is the convention for resource naming: {}",
                repr_str_list(abbreviations)
            )]
        };
        if let Some(content) = self.resources_templates(resources).await?
            && !content.is_empty()
        {
            concrete.extend(content.iter().map(|(r, c)| format!("{r}:\n{c}")));
        }
        render(
            &format!("{CORE}import_filter.jinja"),
            json!({
                "UNMANAGED_IDS": unmanaged_ids,
                "CONCRETE_IMPLEMENTATION": if concrete.is_empty() { Value::Null } else { json!(concrete.join("\n")) },
            }),
        )
    }

    pub async fn render_import_exceptions(&self) -> AppResult<String> {
        self.fetch_guidelines("import_exceptions").await
    }

    pub async fn render_iac_generator(
        &self,
        operation_type: OperationType,
        resources: &[String],
        abbreviations: &[String],
        include_forbidden_actions: bool,
    ) -> AppResult<String> {
        let mut ctx = self
            .conventions_context(resources, abbreviations, include_forbidden_actions)
            .await?;
        ctx.insert("IS_IMPORT".into(), json!(operation_type == OperationType::Import));
        render(&format!("{CORE}iac_generator.jinja"), Value::Object(ctx))
    }

    pub async fn render_prompt_compositor(
        &self,
        already_selected_templates: Option<&[String]>,
        already_selected_abbreviations: Option<&[String]>,
    ) -> AppResult<String> {
        let abbr = self.fetch_guidelines("abbreviations").await?;
        let resources = self.fetch_guidelines("resources_list").await?;
        let templates = self
            .resources_templates(already_selected_templates.unwrap_or(&[]))
            .await?;
        render(
            &format!("{CORE}prompt_compositor.jinja"),
            json!({
                "AVAILABLE_TEMPLATES_LIST": resources,
                "AVAILABLE_ABBREVIATIONS_LIST": abbr,
                "ALREADY_SELECTED_TEMPLATES": templates,
                "ALREADY_SELECTED_ABBREVIATIONS": already_selected_abbreviations,
            }),
        )
    }

    pub async fn render_compliance_checker(&self, resources: &[String], abbreviations: &[String]) -> AppResult<String> {
        let mut ctx = self.conventions_context(resources, abbreviations, true).await?;
        ctx.insert(
            "REPORT_COMPLIANCE_RULES".into(),
            json!(self.fetch("report", "general", "compliance").await?),
        );
        render(&format!("{CORE}compliance_checker.jinja"), Value::Object(ctx))
    }

    async fn conventions_context(
        &self,
        resources: &[String],
        abbreviations: &[String],
        include_forbidden_actions: bool,
    ) -> AppResult<serde_json::Map<String, Value>> {
        let mut concrete: Vec<String> = if abbreviations.is_empty() {
            vec![String::new()]
        } else {
            vec![format!(
                "This is the convention for resource naming: {}",
                repr_str_list(abbreviations)
            )]
        };
        let terraform_guidelines = self.fetch("terraform", "general", "guidelines").await?;
        let resource_creation = self.fetch_guidelines("resource_creation").await?;
        let forbidden_actions = if include_forbidden_actions {
            Some(self.fetch_guidelines("forbidden_actions").await?)
        } else {
            None
        };
        let networking = self.fetch_guidelines("networking").await?;
        let permissions = self.fetch_guidelines("permissions").await?;
        if let Some(content) = self.resources_templates(resources).await? {
            for (r, c) in &content {
                concrete.push(format!("{r}:\n{c}"));
            }
        }
        let mut ctx = serde_json::Map::new();
        ctx.insert("GENERAL_TERRAFORM_GUIDELINES".into(), json!(terraform_guidelines));
        ctx.insert("FORBIDDEN_ACTIONS".into(), json!(forbidden_actions));
        ctx.insert("RESOURCE_CREATION".into(), json!(resource_creation));
        ctx.insert("NETWORKING".into(), json!(networking));
        ctx.insert("PERMISSIONS".into(), json!(permissions));
        ctx.insert("CONCRETE_IMPLEMENTATION".into(), json!(concrete.join("\n")));
        ctx.insert("CWD".into(), json!(self.cwd));
        Ok(ctx)
    }
}

/// Render a template with an explicit context (parity tests and tools).
pub fn render_raw(template: &str, ctx: Value) -> AppResult<String> {
    render(template, ctx)
}

#[cfg(test)]
mod tests {
    use serde_json::Value;

    /// Every layout rendered by the Python Jinja2 environment, replayed.
    #[test]
    fn renders_like_jinja2() {
        let cases: Vec<Value> = serde_json::from_str(include_str!("../../../testdata/template_cases.json")).unwrap();
        let mut failures = Vec::new();
        for case in &cases {
            let name = case["template"].as_str().unwrap();
            let got = super::render_raw(name, case["context"].clone()).unwrap();
            let expected = case["expected"].as_str().unwrap();
            if got != expected {
                let first = got
                    .chars()
                    .zip(expected.chars())
                    .position(|(a, b)| a != b)
                    .unwrap_or(got.len().min(expected.len()));
                let around = |s: &str| s.chars().skip(first.saturating_sub(40)).take(80).collect::<String>();
                failures.push(format!(
                    "{name} {}: differs at char {first}\n  rust:   {:?}\n  python: {:?}",
                    case["context"].to_string().chars().take(80).collect::<String>(),
                    around(&got),
                    around(expected)
                ));
            }
        }
        assert!(
            failures.is_empty(),
            "{} of {} differ:\n{}",
            failures.len(),
            cases.len(),
            failures.join("\n")
        );
    }
}
