// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

//! The tools the agents call.
//!
//! Static tools (sentinels, reports, external information) are available
//! everywhere; a registry built over a workspace adds the file operations
//! and workspace inspection tools on top. Definitions load from the JSON
//! files in `resources/tools`, in a fixed order: tool order is what the
//! report generator's sentinel index relies on.

pub mod models;

use std::path::{Component, Path, PathBuf};
use std::sync::Arc;

use async_trait::async_trait;
use indexmap::IndexMap;
use serde_json::{Map, Value, json};

use crate::domain::dto::{ToolCall, ToolDefinition, ToolResult};
use crate::domain::ports::{FileSystem, Git, ToolRegistry};
use crate::domain::value_objects::{SearchResult, TerraformDoc};
use crate::infrastructure::external::registry::TerraformRegistryClient;
use crate::infrastructure::external::summarizer::SearchResultsSummarizer;
use crate::infrastructure::llm::sidecar::{SidecarClient, SidecarError};
use crate::shared::config::SystemConfig;
use crate::shared::constants::ToolContext;
use crate::shared::error::{AppError, AppResult, ErrorKind};
use crate::shared::pyfmt::{self, str_value};

const TOOL_FILES: &[(&str, &str)] = &[
    (
        "requests_filter.json",
        include_str!("../../../resources/tools/requests_filter.json"),
    ),
    (
        "task_splitter.json",
        include_str!("../../../resources/tools/task_splitter.json"),
    ),
    (
        "filter_reconciliation.json",
        include_str!("../../../resources/tools/filter_reconciliation.json"),
    ),
    (
        "prompt_compositor.json",
        include_str!("../../../resources/tools/prompt_compositor.json"),
    ),
    (
        "target_generator.json",
        include_str!("../../../resources/tools/target_generator.json"),
    ),
    (
        "report_generator.json",
        include_str!("../../../resources/tools/report_generator.json"),
    ),
    (
        "pr_generator.json",
        include_str!("../../../resources/tools/pr_generator.json"),
    ),
    (
        "external_information.json",
        include_str!("../../../resources/tools/external_information.json"),
    ),
    (
        "task_completion.json",
        include_str!("../../../resources/tools/task_completion.json"),
    ),
    (
        "iac_import.json",
        include_str!("../../../resources/tools/iac_import.json"),
    ),
    (
        "compliance_checker.json",
        include_str!("../../../resources/tools/compliance_checker.json"),
    ),
    (
        "file_manipulation.json",
        include_str!("../../../resources/tools/file_manipulation.json"),
    ),
    (
        "workspace_inspection.json",
        include_str!("../../../resources/tools/workspace_inspection.json"),
    ),
];

fn tool_file(name: &str) -> &'static str {
    TOOL_FILES
        .iter()
        .find(|(n, _)| *n == name)
        .map(|(_, c)| *c)
        .expect("bundled tool file")
}

fn static_files() -> Vec<(&'static str, ToolContext)> {
    vec![
        ("requests_filter.json", ToolContext::RequestsFilter),
        ("task_splitter.json", ToolContext::TaskSplitter),
        ("filter_reconciliation.json", ToolContext::FilterReconciliation),
        ("prompt_compositor.json", ToolContext::PromptCompositor),
        ("target_generator.json", ToolContext::TargetGenerator),
        ("report_generator.json", ToolContext::ReportGenerator),
        ("pr_generator.json", ToolContext::PrGenerator),
        ("external_information.json", ToolContext::ExternalInformation),
        ("task_completion.json", ToolContext::GeneralTaskCompletion),
        ("iac_import.json", ToolContext::ImportAddresses),
        ("compliance_checker.json", ToolContext::ComplianceCheck),
    ]
}

fn params_error(message: impl Into<String>, code: u16) -> AppError {
    AppError::kind(ErrorKind::ToolInferenceParams, message, code)
}

/// `params[key]`: a missing key is Python's KeyError, whose `str()` is the
/// quoted key.
fn require<'a>(params: &'a Map<String, Value>, key: &str) -> AppResult<&'a Value> {
    params.get(key).ok_or_else(|| AppError::missing_key(key))
}

/// `params.get(key, default)`.
fn get_or(params: &Map<String, Value>, key: &str, default: Value) -> Value {
    params.get(key).cloned().unwrap_or(default)
}

/// Truthiness, for `params.get(k) or default`.
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

/// `os.path.realpath` for an absolute path, non-strict: symlinks resolved
/// as far as the path exists, `..` applied after each resolution.
pub fn realpath(path: &Path) -> PathBuf {
    let mut pending: std::collections::VecDeque<std::ffi::OsString> = path
        .components()
        .filter_map(|c| match c {
            Component::RootDir | Component::Prefix(_) => None,
            other => Some(other.as_os_str().to_os_string()),
        })
        .collect();
    let mut resolved = PathBuf::from("/");
    let mut budget = 40;
    while let Some(name) = pending.pop_front() {
        if name == "." || name.is_empty() {
            continue;
        }
        if name == ".." {
            resolved.pop();
            continue;
        }
        let candidate = resolved.join(&name);
        match std::fs::symlink_metadata(&candidate) {
            Ok(meta) if meta.file_type().is_symlink() && budget > 0 => {
                budget -= 1;
                match std::fs::read_link(&candidate) {
                    Ok(target) => {
                        if target.is_absolute() {
                            resolved = PathBuf::from("/");
                        }
                        let mut prefix: Vec<std::ffi::OsString> = target
                            .components()
                            .filter_map(|c| match c {
                                Component::RootDir | Component::Prefix(_) => None,
                                other => Some(other.as_os_str().to_os_string()),
                            })
                            .collect();
                        prefix.extend(pending.drain(..));
                        pending = prefix.into();
                    }
                    Err(_) => resolved = candidate,
                }
            }
            _ => resolved = candidate,
        }
    }
    resolved
}

struct Workspace {
    filesystem: Arc<dyn FileSystem>,
    git: Arc<dyn Git>,
}

pub struct ToolRegistryImpl {
    definitions: IndexMap<String, ToolDefinition>,
    workspace: Option<Workspace>,
    summarizer: SearchResultsSummarizer,
    sidecar: SidecarClient,
    registry: TerraformRegistryClient,
    cfg: &'static SystemConfig,
}

impl ToolRegistryImpl {
    fn load(files: &[(&'static str, ToolContext)]) -> IndexMap<String, ToolDefinition> {
        let mut defs = IndexMap::new();
        for (file, context) in files {
            let data: Value = serde_json::from_str(tool_file(file)).expect("bundled tool JSON parses");
            for tool in data.as_array().expect("tool file is a list") {
                let def = ToolDefinition {
                    name: tool["name"].as_str().expect("tool name").to_string(),
                    description: tool["description"].as_str().unwrap_or("").to_string(),
                    parameters: tool["parameters"].clone(),
                    context: *context,
                    single_use: tool["single_use"].as_bool().unwrap_or(false),
                    mutates_workspace: tool["mutates_workspace"].as_bool().unwrap_or(false),
                };
                tracing::info!("Loaded tool: {} from {file}", def.name);
                defs.insert(def.name.clone(), def);
            }
        }
        defs
    }

    /// The registry without workspace tools.
    pub fn new_static(cfg: &'static SystemConfig, summarizer: SearchResultsSummarizer, sidecar: SidecarClient) -> Self {
        Self {
            definitions: Self::load(&static_files()),
            workspace: None,
            summarizer,
            sidecar,
            registry: TerraformRegistryClient::new(),
            cfg,
        }
    }

    /// The registry over a workspace: file and inspection tools first.
    pub fn new_workspace(
        cfg: &'static SystemConfig,
        filesystem: Arc<dyn FileSystem>,
        git: Arc<dyn Git>,
        summarizer: SearchResultsSummarizer,
        sidecar: SidecarClient,
    ) -> Self {
        let mut files = vec![
            ("file_manipulation.json", ToolContext::FileOperations),
            ("workspace_inspection.json", ToolContext::WorkspaceInspection),
        ];
        files.extend(static_files());
        Self {
            definitions: Self::load(&files),
            workspace: Some(Workspace { filesystem, git }),
            summarizer,
            sidecar,
            registry: TerraformRegistryClient::new(),
            cfg,
        }
    }

    fn ws(&self) -> AppResult<&Workspace> {
        self.workspace
            .as_ref()
            .ok_or_else(|| AppError::internal("workspace tool without a workspace"))
    }

    async fn dispatch(&self, name: &str, params: &Map<String, Value>) -> Option<AppResult<Value>> {
        Some(match name {
            "generate_terraform_plan_report" => self.report(
                &models::TERRAFORM_PLAN_REPORT,
                params,
                &["summary", "detailed_changes", "potential_impact", "estimated_costs"],
                400,
            ),
            "generate_terraform_drift_report" => self.drift_report(params),
            "generate_terraform_apply_report" => self.report(
                &models::TERRAFORM_APPLY_REPORT,
                params,
                &[
                    "summary",
                    "status",
                    "execution_summary",
                    "resource_changes",
                    "recommendations",
                ],
                400,
            ),
            "generate_terraform_import_report" => self.report(
                &models::TERRAFORM_IMPORT_REPORT,
                params,
                &[
                    "summary",
                    "status",
                    "execution_summary",
                    "imported_resources",
                    "excluded_resources",
                    "state_alignment",
                    "recommendations",
                ],
                500,
            ),
            "requests_filter" => Self::requests_filter(params),
            "generate_pull_request" => Self::pr_generator(params),
            "construct_information" => Self::construct_information(params),
            "generate_terraform_targets" => Self::target_generator(params),
            "report_decomposed_task_operations" => Self::task_splitter(params),
            "report_reconciliation_verdicts" => Self::reconciliation_verdicts(params),
            "task_complete" => Self::task_completion(params),
            "import_addresses" => Self::import_addresses(params),
            "report_compliance_findings" => Self::compliance_findings(params),
            "web_search" => self.web_search(params).await,
            "terraform_docs" => self.terraform_docs(params).await,
            _ if self.workspace.is_some() => match name {
                "write_to_file" => self.write_file(params),
                "replace_in_file" => self.replace_file(params),
                "delete_file" => self.delete_file(params),
                "read_file" => self.read_file(params),
                "list_dir" => self.list_dir(params),
                "bulk_grep_search" => self.grep_search(params),
                "diff_history" => self.diff_history().await,
                _ => return None,
            },
            _ => return None,
        })
    }

    // --- sentinel / domain tools --------------------------------------------------

    fn report(&self, model: &models::Model, params: &Map<String, Value>, keys: &[&str], code: u16) -> AppResult<Value> {
        let mut input = Map::new();
        for k in keys {
            input.insert((*k).into(), require(params, k)?.clone());
        }
        models::validate_model(model, &Value::Object(input)).map_err(|e| params_error(e, code))
    }

    fn drift_report(&self, params: &Map<String, Value>) -> AppResult<Value> {
        let mut input = Map::new();
        for k in ["summary", "status", "remediated_resources"] {
            input.insert(k.into(), require(params, k)?.clone());
        }
        input.insert(
            "unreconciled_drift".into(),
            get_or(params, "unreconciled_drift", json!([])),
        );
        input.insert(
            "whitelisted_exceptions".into(),
            get_or(params, "whitelisted_exceptions", json!([])),
        );
        models::validate_model(&models::TERRAFORM_DRIFT_REPORT, &Value::Object(input)).map_err(|e| params_error(e, 400))
    }

    fn target_generator(params: &Map<String, Value>) -> AppResult<Value> {
        let targets = require(params, "targets")?;
        let explanation = get_or(params, "explanation", json!(""));
        if !targets.is_array() {
            return Err(params_error(
                format!(
                    "Target generation inference hasn't returned the expected structure. got={}",
                    str_value(targets)
                ),
                400,
            ));
        }
        Ok(json!({"targets": targets, "explanation": explanation}))
    }

    fn requests_filter(params: &Map<String, Value>) -> AppResult<Value> {
        let status = require(params, "status")?;
        let explanation = require(params, "explanation")?;
        if !status.is_boolean() {
            return Err(params_error(
                format!(
                    "Requests filter inference hasn't returned the expected structure. got={}",
                    str_value(status)
                ),
                400,
            ));
        }
        Ok(json!({"status": status, "explanation": explanation}))
    }

    fn pr_generator(params: &Map<String, Value>) -> AppResult<Value> {
        let title = params.get("title");
        let description = params.get("description");
        match (title, description) {
            (Some(Value::String(t)), Some(Value::String(d))) => Ok(json!({"title": t, "description": d})),
            _ => Err(params_error(
                format!(
                    "PR generation inference hasn't returned the expected structure. got={}",
                    pyfmt::repr_value(&Value::Object(params.clone()))
                ),
                400,
            )),
        }
    }

    fn construct_information(params: &Map<String, Value>) -> AppResult<Value> {
        let templates = require(params, "templates")?;
        let abbreviations = require(params, "abbreviations")?;
        let explanation = get_or(params, "explanation", json!(""));
        Ok(json!({"templates": templates, "abbreviations": abbreviations, "explanation": explanation}))
    }

    fn task_completion(params: &Map<String, Value>) -> AppResult<Value> {
        let status = require(params, "status")?;
        let summary = require(params, "summary")?;
        Ok(json!({"status": status, "summary": summary}))
    }

    fn task_splitter(params: &Map<String, Value>) -> AppResult<Value> {
        let operations = require(params, "operations")?;
        let explanation = get_or(params, "explanation", json!(""));
        if !operations.is_array() {
            return Err(params_error(
                format!(
                    "Task Splitter inference hasn't returned the expected structure. got={}",
                    str_value(operations)
                ),
                400,
            ));
        }
        Ok(json!({"operations": operations, "explanation": explanation}))
    }

    fn reconciliation_verdicts(params: &Map<String, Value>) -> AppResult<Value> {
        let report = models::validate_model(
            &models::RECONCILIATION_REPORT,
            &json!({"verdicts": require(params, "verdicts")?}),
        )
        .map_err(|e| params_error(e, 400))?;
        for verdict in report["verdicts"].as_array().cloned().unwrap_or_default() {
            let index = verdict["index"].as_i64().unwrap_or(0);
            let changes = verdict["changes"].as_array().cloned().unwrap_or_default();
            if changes.is_empty() {
                return Err(params_error(
                    format!("Operation {index} has no changes: list every change it describes."),
                    400,
                ));
            }
            let removed = changes.iter().any(|c| c["reverts_session_change"] == json!(true));
            let kept = changes.iter().any(|c| c["reverts_session_change"] == json!(false));
            let operation = verdict["operation"].as_str().unwrap_or("");
            if removed && kept && pyfmt::strip(operation).is_empty() {
                return Err(params_error(
                    format!(
                        "Operation {index} keeps some changes and removes others, so `operation` must hold its rewrite without the removed ones."
                    ),
                    400,
                ));
            }
        }
        Ok(report)
    }

    fn import_addresses(params: &Map<String, Value>) -> AppResult<Value> {
        let summary = require(params, "summary")?;
        let imports = require(params, "imports")?;
        if !imports.is_array() {
            return Err(params_error(
                format!(
                    "IAC import inference hasn't returned the expected structure. got={}",
                    str_value(imports)
                ),
                500,
            ));
        }
        Ok(json!({"summary": summary, "imports": imports}))
    }

    fn compliance_findings(params: &Map<String, Value>) -> AppResult<Value> {
        let violations = require(params, "violations")?;
        // Read before validation, as the Python handler did: a malformed
        // list fails here with the language's own error, not pydantic's.
        let mut failing = false;
        match violations {
            Value::Array(items) => {
                for v in items {
                    let Value::Object(m) = v else {
                        return Err(AppError::internal(format!(
                            "{} indices must be integers or slices, not str",
                            match v {
                                Value::String(_) => "string",
                                Value::Array(_) => "list",
                                _ => "object",
                            }
                        )));
                    };
                    let severity = m.get("severity").ok_or_else(|| AppError::missing_key("severity"))?;
                    if severity == "error" || severity == "critical" {
                        failing = true;
                        break;
                    }
                }
            }
            Value::Object(m) => {
                // Iterating a dict yields its keys (strings).
                if !m.is_empty() {
                    return Err(AppError::internal("string indices must be integers, not 'str'"));
                }
            }
            other => {
                return Err(AppError::internal(format!(
                    "'{}' object is not iterable",
                    match other {
                        Value::Null => "NoneType",
                        Value::Bool(_) => "bool",
                        Value::Number(n) if n.is_f64() => "float",
                        Value::Number(_) => "int",
                        _ => "str",
                    }
                )));
            }
        }
        let input = json!({
            "passed": !failing,
            "violations": violations,
            "summary": require(params, "summary")?,
            "checked_rules": require(params, "checked_rules")?,
        });
        models::validate_model(&models::COMPLIANCE_CHECK_REPORT, &input).map_err(|e| params_error(e, 400))
    }

    // --- external information ---------------------------------------------------------

    fn no_results(query: &Value, reason: &str) -> Value {
        json!({
            "query": query,
            "result": format!(
                "{reason} Search again with a different query — other keywords, synonyms, or a broader or narrower scope. Do not repeat this query."
            ),
        })
    }

    async fn web_search(&self, params: &Map<String, Value>) -> AppResult<Value> {
        let query = require(params, "query")?.clone();
        let q = str_value(&query);
        if self.cfg.web_search.provider.is_empty() {
            return Ok(json!({
                "query": query,
                "result": "Web search is unavailable: no provider configured. Do NOT retry web_search.",
            }));
        }
        let results = match self.sidecar.search(&q).await {
            Ok(r) => r,
            Err(e) => {
                let message = match e {
                    SidecarError::Problem { detail, .. } => detail,
                    SidecarError::Transport(m) => {
                        tracing::error!("Web search via {} failed: {m}", self.cfg.web_search.provider);
                        format!("the '{}' search engine call failed", self.cfg.web_search.provider)
                    }
                };
                return Ok(json!({
                    "query": query,
                    "result": format!("Web search is unavailable: {message}. Do NOT retry web_search."),
                }));
            }
        };
        if results.is_empty() {
            return Ok(Self::no_results(
                &query,
                &format!("Web search with query '{q}' returned no content."),
            ));
        }
        match self.summarized_search_results(&q, &results).await {
            None => Ok(Self::no_results(
                &query,
                &format!("Web search with query '{q}' returned no relevant content."),
            )),
            Some(s) => Ok(json!({"query": query, "result": s})),
        }
    }

    /// Condense every hit, rank them, return the top summaries. `None`
    /// means none answers the query; a summarizer *failure* degrades to the
    /// raw results so the tool call never fails on account of the reduction.
    async fn summarized_search_results(&self, query: &str, results: &[SearchResult]) -> Option<String> {
        let (selected, discarded) = match self.summarizer.best(query, results).await {
            Ok(v) => v,
            Err(e) => {
                tracing::warn!("Search result summarization failed, returning raw results: {e}");
                return Some(
                    results
                        .iter()
                        .map(|r| format!("- {}: {} ({})", r.title, r.content, r.url))
                        .collect::<Vec<_>>()
                        .join("\n"),
                );
            }
        };
        if selected.is_empty() {
            tracing::debug!(
                "web_search '{query}' found no relevant page among {} result(s).",
                results.len()
            );
            return None;
        }
        if !discarded.is_empty() {
            tracing::debug!(
                "web_search '{query}' discarded {} source(s) considered less relevant: {}",
                discarded.len(),
                discarded
                    .iter()
                    .map(|s| format!("{} ({})", s.result.title, s.result.url))
                    .collect::<Vec<_>>()
                    .join("; ")
            );
        }
        Some(
            selected
                .iter()
                .map(|s| format!("- {}: {} ({})", s.result.title, s.summary, s.result.url))
                .collect::<Vec<_>>()
                .join("\n"),
        )
    }

    async fn terraform_docs(&self, params: &Map<String, Value>) -> AppResult<Value> {
        let provider = require(params, "provider")?.clone();
        let resource_type = require(params, "resource_type")?.clone();
        let focus = require(params, "focus")?.clone();
        let version = params
            .get("version")
            .filter(|v| truthy(v))
            .cloned()
            .unwrap_or(Value::Null);
        let section = params
            .get("section")
            .filter(|v| truthy(v))
            .cloned()
            .unwrap_or(json!("full"));
        let kind = params
            .get("kind")
            .filter(|v| truthy(v))
            .cloned()
            .unwrap_or(json!("resource"));
        let section_ok = section == "full" || section == "import";
        let kind_ok = kind == "resource" || kind == "data_source";
        if !section_ok || !kind_ok {
            return Err(params_error(
                format!(
                    "`section` must be 'full' or 'import' and `kind` must be 'resource' or 'data_source'. got section={}, kind={}",
                    str_value(&section),
                    str_value(&kind)
                ),
                400,
            ));
        }
        if section == "import" && kind == "data_source" {
            return Err(params_error(
                "Data sources cannot be imported and have no Import section; use section 'full' for a data source.",
                400,
            ));
        }
        let focus = match &focus {
            Value::String(s) if !pyfmt::strip(s).is_empty() => pyfmt::strip(s).to_string(),
            _ => {
                return Err(params_error(
                    "`focus` must say what you need from the documentation.",
                    400,
                ));
            }
        };
        let mut answer = Map::new();
        answer.insert("provider".into(), provider.clone());
        answer.insert("version".into(), version.clone());
        answer.insert("resource_type".into(), resource_type.clone());
        answer.insert("section".into(), section.clone());
        let with_result = |mut answer: Map<String, Value>, result: String| {
            answer.insert("result".into(), Value::String(result));
            Value::Object(answer)
        };

        let provider_s = match &provider {
            Value::String(s) => s.clone(),
            other => {
                return Err(AppError::internal(format!(
                    "'{}' object has no attribute 'strip'",
                    py_type(other)
                )));
            }
        };
        let resource_s = match &resource_type {
            Value::String(s) => s.clone(),
            other => {
                return Err(AppError::internal(format!(
                    "'{}' object has no attribute 'strip'",
                    py_type(other)
                )));
            }
        };
        let version_s = match &version {
            Value::Null => None,
            Value::String(s) => Some(s.clone()),
            other => {
                return Err(AppError::internal(format!(
                    "'{}' object has no attribute 'strip'",
                    py_type(other)
                )));
            }
        };
        let doc = match self
            .registry
            .fetch(&provider_s, &resource_s, version_s.as_deref(), kind == "data_source")
            .await
        {
            Ok(d) => d,
            Err(e) if e.is(ErrorKind::TerraformDocsNotFound) => {
                return Ok(with_result(
                    answer,
                    format!(
                        "{} Check the provider source, version and type name before calling terraform_docs again; do not repeat this call.",
                        e.message
                    ),
                ));
            }
            Err(e) if e.is(ErrorKind::TerraformRegistry) => {
                return Ok(with_result(
                    answer,
                    format!(
                        "Terraform documentation is unavailable: {}. Do NOT retry terraform_docs; use web_search instead.",
                        e.message
                    ),
                ));
            }
            Err(e) => return Err(e),
        };
        answer.insert("provider".into(), json!(doc.source));
        answer.insert("version".into(), json!(doc.version));
        answer.insert("url".into(), json!(doc.url));
        let mut content = doc.content.clone();
        if section == "import" {
            match TerraformRegistryClient::import_section(&doc.content) {
                Some(s) => content = s,
                None => {
                    return Ok(with_result(
                        answer,
                        format!(
                            "The documentation of {} in {} {} has no Import section: the resource type may not support import.",
                            doc.resource_type, doc.source, doc.version
                        ),
                    ));
                }
            }
        }
        let condensed = self.condensed_docs(&doc, &content, &focus).await;
        Ok(with_result(answer, condensed))
    }

    async fn condensed_docs(&self, doc: &TerraformDoc, content: &str, focus: &str) -> String {
        let content = pyfmt::take_chars(content, TerraformRegistryClient::MAX_DOC_CHARS).to_string();
        let page = SearchResult {
            title: format!("{} ({} {})", doc.resource_type, doc.source, doc.version),
            url: doc.url.clone(),
            content: content.clone(),
        };
        match self
            .summarizer
            .condense(&format!("{}: {focus}", doc.resource_type), &page)
            .await
        {
            Err(e) => {
                tracing::warn!("Terraform docs summarization failed, returning the raw page: {e}");
                content
            }
            Ok(None) => format!(
                "The documentation of {} in {} {} has nothing on '{focus}'. Ask with a different focus; do not repeat this one.",
                doc.resource_type, doc.source, doc.version
            ),
            Ok(Some(summary)) => summary,
        }
    }

    // --- workspace tools ----------------------------------------------------------------

    /// Normalize a tool path to one relative to the working directory.
    /// Absolute paths are accepted when they point inside it; anything
    /// resolving outside, or into an entry Kumoss manages, is rejected.
    fn limit_workspace_boundaries(&self, path: &Value) -> AppResult<String> {
        let ws = self.ws()?;
        let path = match path {
            Value::String(s) => s.clone(),
            other => {
                return Err(AppError::internal(format!(
                    "unsupported operand type(s) for /: 'PosixPath' and '{}'",
                    py_type(other)
                )));
            }
        };
        let root = realpath(&ws.filesystem.project_root());
        let resolved = realpath(&root.join(&path));
        let Ok(relative) = resolved.strip_prefix(&root) else {
            return Err(params_error(
                format!(
                    "Path '{path}' is outside the working directory '{}'. Only files inside the working directory are accessible; use paths relative to it (e.g. 'main.tf', '.').",
                    root.display()
                ),
                400,
            ));
        };
        let protected = ws.filesystem.protected_names();
        if relative
            .components()
            .any(|c| protected.iter().any(|p| c.as_os_str() == p.as_str()))
        {
            return Err(params_error(
                format!("Path '{path}' is managed by Kumoss and is not accessible."),
                403,
            ));
        }
        let rel = relative.to_string_lossy().to_string();
        Ok(if rel.is_empty() { ".".into() } else { rel })
    }

    fn string_param(value: &Value, target_file: &str, verb: &str) -> AppResult<String> {
        match value {
            Value::String(s) => Ok(s.clone()),
            other => Err(AppError::new(
                format!(
                    "Error {verb} file {target_file} - TypeError('write() argument must be str, not {}')",
                    py_type(other)
                ),
                500,
            )),
        }
    }

    fn write_file(&self, params: &Map<String, Value>) -> AppResult<Value> {
        let target = require(params, "target_file")?;
        let content = require(params, "content")?;
        let target = self.limit_workspace_boundaries(target)?;
        let content = Self::string_param(content, &target, "writing to")?;
        self.ws()?.filesystem.write_file(&target, &content, true)?;
        Ok(json!({"file": target}))
    }

    fn replace_file(&self, params: &Map<String, Value>) -> AppResult<Value> {
        let target = require(params, "target_file")?;
        let diff = require(params, "diff")?;
        let target = self.limit_workspace_boundaries(target)?;
        let diff = match diff {
            Value::String(s) => s.clone(),
            other => {
                return Err(AppError::new(
                    format!(
                        "Failed to replace content in file {target}: AttributeError(\"'{}' object has no attribute 'splitlines'\")",
                        py_type(other)
                    ),
                    500,
                ));
            }
        };
        self.ws()?.filesystem.replace_in_file(&target, &diff)?;
        Ok(json!({"file": target}))
    }

    fn delete_file(&self, params: &Map<String, Value>) -> AppResult<Value> {
        let target = self.limit_workspace_boundaries(require(params, "target_file")?)?;
        self.ws()?.filesystem.delete_file(&target)?;
        Ok(json!({"file": target}))
    }

    fn read_file(&self, params: &Map<String, Value>) -> AppResult<Value> {
        let target = self.limit_workspace_boundaries(require(params, "target_file")?)?;
        let content = match self.ws()?.filesystem.read_file(&target) {
            Ok(c) => c,
            Err(e) if e.is(ErrorKind::CustomFileNotFound) => {
                return Err(params_error(
                    format!(
                        "{target} was not present in the authoritative directory listing. Do not probe guessed filenames."
                    ),
                    404,
                ));
            }
            Err(e) => return Err(e),
        };
        Ok(json!({"file": target, "content": content}))
    }

    fn list_dir(&self, params: &Map<String, Value>) -> AppResult<Value> {
        let relative = self.limit_workspace_boundaries(require(params, "relative_workspace_path")?)?;
        let mut items = self.ws()?.filesystem.list_directory(&relative)?;
        items.sort_by(|a, b| {
            let pa: Vec<String> = a
                .components()
                .map(|c| c.as_os_str().to_string_lossy().into_owned())
                .collect();
            let pb: Vec<String> = b
                .components()
                .map(|c| c.as_os_str().to_string_lossy().into_owned())
                .collect();
            pa.cmp(&pb)
        });
        let name = |p: &PathBuf| {
            p.file_name()
                .map(|n| n.to_string_lossy().into_owned())
                .unwrap_or_default()
        };
        Ok(json!({
            "path": relative,
            "files": items.iter().filter(|i| i.is_file()).map(name).collect::<Vec<_>>(),
            "directories": items.iter().filter(|i| i.is_dir()).map(name).collect::<Vec<_>>(),
        }))
    }

    fn grep_search(&self, params: &Map<String, Value>) -> AppResult<Value> {
        const MAX_GREP_MATCHES: usize = 50;
        let searches = require(params, "searches")?;
        if !truthy(searches) {
            return Err(params_error("Invalid request. At least one search is required.", 400));
        }
        let Value::Array(searches) = searches else {
            return Err(AppError::internal("string indices must be integers, not 'str'"));
        };
        let ws = self.ws()?;
        let workspace_path = format!("{}/", ws.filesystem.project_root().display());
        let mut out = Vec::new();
        for s in searches {
            let Value::Object(s) = s else {
                return Err(AppError::internal("string indices must be integers, not 'str'"));
            };
            let query = require(s, "query")?;
            let include = s.get("include_pattern").cloned().unwrap_or(Value::Null);
            let exclude = s.get("exclude_pattern").cloned().unwrap_or(Value::Null);
            let case_sensitive = s.get("case_sensitive").cloned().unwrap_or(json!(false));
            let pattern_arg = |v: &Value| -> Option<String> { if truthy(v) { Some(str_value(v)) } else { None } };
            let raw = ws.filesystem.search_files(
                &str_value(query),
                pattern_arg(&include).as_deref(),
                pattern_arg(&exclude).as_deref(),
                truthy(&case_sensitive),
            )?;
            let matches: Vec<String> = raw
                .into_iter()
                .map(|m| m.strip_prefix(&workspace_path).map(str::to_string).unwrap_or(m))
                .collect();
            out.push(json!({
                "query": query,
                "include_pattern": include,
                "exclude_pattern": exclude,
                "case_sensitive": case_sensitive,
                "match_count": matches.len(),
                "truncated": matches.len() > MAX_GREP_MATCHES,
                "matches": matches.iter().take(MAX_GREP_MATCHES).collect::<Vec<_>>(),
            }));
        }
        Ok(Value::Array(out))
    }

    async fn diff_history(&self) -> AppResult<Value> {
        let ws = self.ws()?;
        let mut result: Vec<Value> = Vec::new();
        let diff = ws.git.show_diff(false, false, None).await?;
        if !diff.is_empty() {
            result.push(Value::String(diff));
        }
        let mut untracked: Vec<Value> = Vec::new();
        for file in ws.git.get_untracked_files().await? {
            let content = self
                .limit_workspace_boundaries(&Value::String(file.clone()))
                .and_then(|p| ws.filesystem.read_file(&p));
            match content {
                Ok(c) => {
                    if !c.is_empty() {
                        untracked.push(Value::String(format!("{file}:\n{c}")));
                    }
                }
                Err(e) => tracing::warn!("Error reading file: {}", e.message),
            }
        }
        if !untracked.is_empty() {
            result.push(Value::Array(untracked));
        }
        Ok(json!({"history_available": true, "changes": result}))
    }
}

fn py_type(v: &Value) -> &'static str {
    match v {
        Value::Null => "NoneType",
        Value::Bool(_) => "bool",
        Value::Number(n) if n.is_f64() => "float",
        Value::Number(_) => "int",
        Value::String(_) => "str",
        Value::Array(_) => "list",
        Value::Object(_) => "dict",
    }
}

#[async_trait]
impl ToolRegistry for ToolRegistryImpl {
    fn get_available_tools(&self, context: ToolContext) -> AppResult<Vec<ToolDefinition>> {
        let tools: Vec<ToolDefinition> = self
            .definitions
            .values()
            .filter(|t| t.context == context)
            .cloned()
            .collect();
        if tools.is_empty() {
            return Err(AppError::kind(
                ErrorKind::ToolDefinitionContextNotFound,
                format!("Tool definition not found for context={}", context.py_str()),
                404,
            ));
        }
        Ok(tools)
    }

    fn get_tool_definition(&self, tool_name: &str) -> AppResult<ToolDefinition> {
        self.definitions.get(tool_name).cloned().ok_or_else(|| {
            AppError::kind(
                ErrorKind::ToolDefinitionNameNotFound,
                format!("Tool definition name not found. got={tool_name}"),
                404,
            )
        })
    }

    async fn execute_tool(&self, call: &ToolCall) -> ToolResult {
        let failed = |message: String| ToolResult {
            name: call.name.clone(),
            tool_call_id: call.id.clone(),
            success: false,
            result: Value::Null,
            error_message: Some(message),
        };
        let params = call.params().clone();
        match self.dispatch(&call.name, &params).await {
            None => failed(format!("Tool {} not found", call.name)),
            Some(Ok(result)) => ToolResult {
                name: call.name.clone(),
                tool_call_id: call.id.clone(),
                success: true,
                result,
                error_message: None,
            },
            Some(Err(e)) => {
                tracing::error!("Tool {} failed: {}", call.name, e.message);
                failed(e.message)
            }
        }
    }

    fn validate_tool_parameters(&self, tool_name: &str, parameters: &Value) -> bool {
        let Some(def) = self.definitions.get(tool_name) else {
            return false;
        };
        let required: Vec<String> = def
            .parameters
            .get("required")
            .and_then(Value::as_array)
            .map(|r| r.iter().filter_map(|v| v.as_str().map(str::to_string)).collect())
            .unwrap_or_default();
        let keys: Vec<&String> = match parameters {
            Value::Object(m) => m.keys().collect(),
            _ => Vec::new(),
        };
        for param in required {
            if !keys.iter().any(|k| **k == param) {
                tracing::error!("Missing required parameter {param} for tool {tool_name}");
                return false;
            }
        }
        true
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn realpath_handles_dotdot_and_missing() {
        let dir = tempfile::tempdir().unwrap();
        let root = realpath(dir.path());
        assert_eq!(realpath(&root.join("a/../b")), root.join("b"));
        assert_eq!(realpath(&root.join("missing/x/../y")), root.join("missing/y"));
        std::os::unix::fs::symlink("/etc", root.join("link")).unwrap();
        assert_eq!(realpath(&root.join("link/hosts")), PathBuf::from("/etc/hosts"));
    }

    #[test]
    fn tool_order_matches_python() {
        let defs = ToolRegistryImpl::load(&static_files());
        let reports: Vec<&str> = defs
            .values()
            .filter(|t| t.context == ToolContext::ReportGenerator)
            .map(|t| t.name.as_str())
            .collect();
        assert_eq!(
            reports,
            [
                "generate_terraform_plan_report",
                "generate_terraform_drift_report",
                "generate_terraform_apply_report",
                "generate_terraform_import_report"
            ]
        );
    }

    #[test]
    fn domain_handlers() {
        let p = |v: Value| v.as_object().unwrap().clone();
        assert!(ToolRegistryImpl::target_generator(&p(json!({"targets": "x"}))).is_err());
        assert_eq!(
            ToolRegistryImpl::target_generator(&p(json!({"targets": ["a"]}))).unwrap(),
            json!({"targets": ["a"], "explanation": ""})
        );
        let err = ToolRegistryImpl::requests_filter(&p(json!({"status": "yes", "explanation": "e"}))).unwrap_err();
        assert_eq!(
            err.message,
            "Requests filter inference hasn't returned the expected structure. got=yes"
        );
        let err = ToolRegistryImpl::task_completion(&p(json!({"status": "done"}))).unwrap_err();
        assert_eq!(err.message, "'summary'");
        let ok = ToolRegistryImpl::compliance_findings(&p(json!({
            "passed": true,
            "violations": [{"rule_id": "r", "severity": "critical", "message": "m"}],
            "summary": "s",
            "checked_rules": ["r"]
        })))
        .unwrap();
        assert_eq!(ok["passed"], json!(false));
        assert_eq!(ok["violations"][0]["resource"], Value::Null);
    }

    #[test]
    fn reconciliation_requires_rewrite_when_mixed() {
        let p = json!({"verdicts": [{"index": 1, "changes": [
            {"description": "a", "reverts_session_change": true, "reason": "r"},
            {"description": "b", "reverts_session_change": false, "reason": "r"}
        ]}]});
        let err = ToolRegistryImpl::reconciliation_verdicts(p.as_object().unwrap()).unwrap_err();
        assert!(err.message.starts_with("Operation 1 keeps some changes"));
    }
}
