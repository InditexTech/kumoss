// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

//! OpenTelemetry tracing with OpenInference semantics, exported to Phoenix.
//!
//! One tracer provider per Phoenix project (environment × operation). A
//! `PhoenixTracer` is tied to the lifetime of a single session run and is
//! carried in a task-local, so every chain, LLM, tool and terraform span of
//! that run carries the session's metadata.
//!
//! Span topology follows the Python tracer: chains and terraform verbs are
//! root spans; LLM and tool spans hang off the most recently started chain.

use std::collections::HashMap;
use std::sync::{Arc, Mutex, OnceLock};
use std::time::SystemTime;

use indexmap::IndexMap;
use opentelemetry::trace::{Span as _, SpanContext, Status, TraceContextExt, Tracer as _, TracerProvider as _};
use opentelemetry::{Context, KeyValue, Value as OtelValue};
use opentelemetry_otlp::WithExportConfig;
use opentelemetry_sdk::Resource;
use opentelemetry_sdk::trace::{BatchSpanProcessor, SdkTracerProvider, Span, Tracer};
use serde_json::{Map, Value, json};
use uuid::Uuid;

use crate::domain::dto::{LlmMetadata, LlmResponse, ToolCall, ToolDefinition, ToolResult};
use crate::domain::entities::{History, TurnAssistant, TurnUser};
use crate::domain::ports::InferenceRequest;
use crate::shared::config::SystemConfig;
use crate::shared::constants::{OperationType, TerraformProvider, TracerProject};
use crate::shared::error::{AppError, AppResult, ErrorKind};
use crate::shared::pyfmt;

const MIME_TEXT: &str = "text/plain";
const MIME_JSON: &str = "application/json";

static PROVIDERS: OnceLock<HashMap<TracerProject, SdkTracerProvider>> = OnceLock::new();

/// Build every project's provider. Must run outside the async runtime: the
/// OTLP exporter uses a blocking HTTP client on the batch processor's own
/// thread.
pub fn init_providers(cfg: &SystemConfig) {
    let mut providers = HashMap::new();
    let limit = usize::try_from(cfg.telemetry.otel_attribute_count_limit).unwrap_or(128) as u32;
    for project in TracerProject::ALL {
        let resource = Resource::builder_empty()
            .with_attributes([KeyValue::new("openinference.project.name", project.value())])
            .build();
        let mut builder = SdkTracerProvider::builder()
            .with_resource(resource)
            .with_max_attributes_per_span(limit)
            .with_max_attributes_per_event(limit)
            .with_max_attributes_per_link(limit);
        if cfg.telemetry.otel_console_exporter {
            builder = builder.with_span_processor(
                BatchSpanProcessor::builder(opentelemetry_stdout::SpanExporter::default()).build(),
            );
        }
        match opentelemetry_otlp::SpanExporter::builder()
            .with_http()
            .with_endpoint(cfg.otlp_traces_endpoint())
            .build()
        {
            Ok(exporter) => builder = builder.with_span_processor(BatchSpanProcessor::builder(exporter).build()),
            Err(e) => tracing::warn!("Could not build the OTLP exporter for {}: {e}", project.value()),
        }
        providers.insert(*project, builder.build());
    }
    let _ = PROVIDERS.set(providers);
    tracing::debug!("Tracer providers initialized successfully");
}

/// Flush pending spans and shut down every provider (spans are exported
/// asynchronously; unflushed ones would be lost).
pub fn shutdown_providers() {
    if let Some(providers) = PROVIDERS.get() {
        for p in providers.values() {
            let _ = p.shutdown();
        }
    }
}

fn route_project(environment: &str, operation: OperationType) -> Option<TracerProject> {
    use TracerProject::*;
    Some(match (operation, environment) {
        (OperationType::Generate, "production") => ProTerraformDay2,
        (OperationType::Generate, "development") => DevTerraformDay2,
        (OperationType::Generate, "staging") => PreTerraformDay2,
        (OperationType::Drift, "production") => ProTerraformDrift,
        (OperationType::Drift, "development") => DevTerraformDrift,
        (OperationType::Drift, "staging") => PreTerraformDrift,
        (OperationType::Import, "production") => ProTerraformImport,
        (OperationType::Import, "development") => DevTerraformImport,
        (OperationType::Import, "staging") => PreTerraformImport,
        _ => return None,
    })
}

/// The tracer of one session run.
pub struct PhoenixTracer {
    tracer: Option<Tracer>,
    session_id: String,
    user_id: String,
    cloud: TerraformProvider,
    repo_uri: String,
    iac_path: Option<String>,
    branch_name: String,
    root: Mutex<Option<SpanContext>>,
}

tokio::task_local! {
    static CURRENT: Arc<PhoenixTracer>;
}

impl PhoenixTracer {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        cfg: &SystemConfig,
        session_id: &Uuid,
        user_id: &str,
        cloud: TerraformProvider,
        repo_uri: &str,
        iac_path: Option<&str>,
        operation: OperationType,
        branch_name: &str,
    ) -> Self {
        let tracer = route_project(&cfg.environment, operation).and_then(|project| {
            PROVIDERS
                .get()
                .and_then(|p| p.get(&project))
                .map(|p| p.tracer(project.value()))
        });
        Self {
            tracer,
            session_id: session_id.to_string(),
            user_id: user_id.to_string(),
            cloud,
            repo_uri: repo_uri.to_string(),
            iac_path: iac_path.map(str::to_string),
            branch_name: branch_name.to_string(),
            root: Mutex::new(None),
        }
    }

    /// Run `fut` with this tracer as the current one.
    pub async fn scope<F: std::future::Future>(self: Arc<Self>, fut: F) -> F::Output {
        CURRENT.scope(self, fut).await
    }

    fn metadata(&self, extra: Option<(&str, &str)>) -> Vec<(String, OtelValue)> {
        let mut meta = Map::new();
        meta.insert("session_id".into(), json!(self.session_id));
        meta.insert("user_id".into(), json!(self.user_id));
        meta.insert("cloud".into(), json!(self.cloud.name()));
        meta.insert("repo_uri".into(), json!(self.repo_uri));
        meta.insert("iac_path".into(), json!(self.iac_path));
        meta.insert("branch_name".into(), json!(self.branch_name));
        if let Some((k, v)) = extra {
            meta.insert(k.into(), json!(v));
        }
        vec![
            ("session.id".into(), self.session_id.clone().into()),
            ("user.id".into(), self.user_id.clone().into()),
            ("metadata".into(), pyfmt::json_dumps(&Value::Object(meta)).into()),
        ]
    }

    fn start(
        &self,
        name: String,
        start: Option<SystemTime>,
        parent: Option<SpanContext>,
        attrs: Vec<(String, OtelValue)>,
    ) -> Option<Span> {
        let tracer = self.tracer.as_ref()?;
        // Later writes of a key win, as with a span's attribute dict.
        let mut dedup: IndexMap<String, OtelValue> = IndexMap::new();
        for (k, v) in attrs {
            dedup.insert(k, v);
        }
        let kvs: Vec<KeyValue> = dedup.into_iter().map(|(k, v)| KeyValue::new(k, v)).collect();
        let mut builder = tracer.span_builder(name).with_attributes(kvs);
        if let Some(t) = start {
            builder = builder.with_start_time(t);
        }
        let cx = match parent {
            Some(sc) => Context::new().with_remote_span_context(sc),
            None => Context::new(),
        };
        Some(builder.start_with_context(tracer, &cx))
    }
}

fn finish(span: Option<Span>) {
    if let Some(mut s) = span {
        s.set_status(Status::Ok);
        s.end();
    }
}

fn current() -> Option<Arc<PhoenixTracer>> {
    CURRENT.try_with(|t| t.clone()).ok()
}

// --- payload serialization ------------------------------------------------------

/// A payload as OpenInference input/output: text for strings, JSON otherwise.
fn serialize(payload: &Value) -> (String, &'static str) {
    match payload {
        Value::String(s) => (s.clone(), MIME_TEXT),
        other => (pyfmt::json_dumps_unicode(other), MIME_JSON),
    }
}

fn io_attrs(prefix: &str, payload: &Value) -> Vec<(String, OtelValue)> {
    let (value, mime) = serialize(payload);
    vec![
        (format!("{prefix}.value"), value.into()),
        (format!("{prefix}.mime_type"), mime.to_string().into()),
    ]
}

fn kind_attr(kind: &str) -> (String, OtelValue) {
    ("openinference.span.kind".into(), kind.to_string().into())
}

pub fn tool_result_dict(r: &ToolResult) -> Value {
    json!({
        "name": r.name,
        "tool_call_id": r.tool_call_id,
        "success": r.success,
        "result": r.result,
        "error_message": r.error_message,
    })
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

// --- chains -------------------------------------------------------------------------

/// An open chain span; becomes the parent of later LLM and tool spans.
pub struct ChainSpan(Option<Span>);

/// What a chain returned, for its output attributes.
pub enum ChainOutput<'a> {
    Text(&'a str),
    Tool(&'a ToolResult),
}

pub fn chain_start(prompt_kind: &str, query: &str) -> ChainSpan {
    let Some(t) = current() else {
        return ChainSpan(None);
    };
    let mut attrs = t.metadata(Some(("chain_type", prompt_kind)));
    attrs.push(kind_attr("AGENT"));
    attrs.extend(io_attrs("input", &Value::String(query.to_string())));
    let span = t.start(format!("Chain - {prompt_kind}"), None, None, attrs);
    if let Some(s) = &span {
        *t.root.lock().expect("root lock") = Some(s.span_context().clone());
    }
    ChainSpan(span)
}

pub fn chain_end(mut span: ChainSpan, output: ChainOutput<'_>) {
    let payload = match output {
        ChainOutput::Text(s) => Value::String(s.to_string()),
        ChainOutput::Tool(r) => match &r.result {
            Value::Object(m) => {
                let pick = ["summary", "explanation", "description"]
                    .iter()
                    .filter_map(|k| m.get(*k))
                    .find(|v| truthy(v));
                pick.cloned().unwrap_or_else(|| r.result.clone())
            }
            other => other.clone(),
        },
    };
    if let Some(s) = span.0.as_mut() {
        for (k, v) in io_attrs("output", &payload) {
            s.set_attribute(KeyValue::new(k, v));
        }
    }
    finish(span.0);
}

// --- tools ----------------------------------------------------------------------------

pub fn trace_tool(start: SystemTime, call: &ToolCall, output: &ToolResult) {
    let Some(t) = current() else {
        return;
    };
    let parent = t.root.lock().expect("root lock").clone();
    let mut attrs = t.metadata(None);
    attrs.push(kind_attr("TOOL"));
    attrs.push(("tool.name".into(), call.name.clone().into()));
    let id = if output.tool_call_id.is_empty() {
        call.id.clone()
    } else {
        output.tool_call_id.clone()
    };
    attrs.push(("tool.id".into(), id.into()));
    attrs.push((
        "tool.parameters".into(),
        pyfmt::json_dumps_unicode(&call.parameters).into(),
    ));
    attrs.extend(io_attrs("input", &call.parameters));
    attrs.extend(io_attrs("output", &tool_result_dict(output)));
    finish(t.start(format!("Tool call - {}", call.name), Some(start), parent, attrs));
}

// --- terraform ----------------------------------------------------------------------------

/// One terraform verb: `input` is the verb's keyword arguments.
pub fn trace_terraform(start: SystemTime, operation: &str, ok: bool, summary: &str, input: Value) {
    let Some(t) = current() else {
        return;
    };
    let mut attrs = t.metadata(None);
    attrs.push(kind_attr("EVALUATOR"));
    attrs.extend(io_attrs("input", &input));
    let output = summary.trim_matches('"').trim_matches('\'');
    attrs.extend(io_attrs("output", &Value::String(output.to_string())));
    let name = format!("Terraform {operation} - {}", if ok { "True" } else { "False" });
    finish(t.start(name, Some(start), None, attrs));
}

// --- LLM ----------------------------------------------------------------------------------

pub struct LlmTrace<'a> {
    pub start: SystemTime,
    pub model: &'a str,
    pub model_name: Option<&'a str>,
    pub llm_provider: Option<&'a str>,
    pub invocation_params: &'a Value,
    pub response: &'a LlmResponse,
    pub request: &'a InferenceRequest<'a>,
}

fn oi_provider(litellm_provider: &str) -> Option<&'static str> {
    Some(match litellm_provider {
        "openai" => "openai",
        "anthropic" => "anthropic",
        "cohere" => "cohere",
        "mistral" => "mistralai",
        "vertex_ai" | "vertex_ai_beta" | "gemini" => "google",
        "azure" | "azure_ai" => "azure",
        "bedrock" | "sagemaker" => "aws",
        "xai" => "xai",
        "deepseek" => "deepseek",
        "groq" => "groq",
        "fireworks_ai" => "fireworks",
        "moonshot" => "moonshot",
        "cerebras" => "cerebras",
        "perplexity" => "perplexity",
        "together_ai" => "together",
        _ => return None,
    })
}

fn input_messages(req: &InferenceRequest<'_>) -> Vec<(String, OtelValue)> {
    let mut out: Vec<(String, OtelValue)> = Vec::new();
    let base = "llm.input_messages";
    let text = |out: &mut Vec<(String, OtelValue)>, msg: &str, role: &str, idx: usize| {
        out.push((format!("{base}.{idx}.message.content"), msg.to_string().into()));
        out.push((format!("{base}.{idx}.message.role"), role.to_string().into()));
    };
    let tool_results = |out: &mut Vec<(String, OtelValue)>, results: &[ToolResult], idx: usize| {
        for (i, r) in results.iter().enumerate() {
            out.push((format!("{base}.{}.message.role", idx + i), "tool".to_string().into()));
            out.push((
                format!("{base}.{}.message.tool_call_id", idx + i),
                r.tool_call_id.clone().into(),
            ));
            let content = if r.success {
                pyfmt::str_value(&r.result)
            } else {
                r.error_message.clone().unwrap_or_else(|| "None".into())
            };
            out.push((format!("{base}.{}.message.content", idx + i), content.into()));
        }
    };
    let tool_calls = |out: &mut Vec<(String, OtelValue)>, calls: &[ToolCall], idx: usize| {
        out.push((format!("{base}.{idx}.message.role"), "assistant".to_string().into()));
        for (i, c) in calls.iter().enumerate() {
            let prefix = format!("{base}.{idx}.message.tool_calls.{i}");
            out.push((format!("{prefix}.tool_call.id"), c.id.clone().into()));
            out.push((format!("{prefix}.tool_call.function.name"), c.name.clone().into()));
            out.push((
                format!("{prefix}.tool_call.function.arguments"),
                pyfmt::json_dumps(&c.parameters).into(),
            ));
        }
    };

    let mut idx = 0usize;
    if let Some(system) = req.system_prompt.filter(|s| !s.is_empty()) {
        text(&mut out, system, "system", idx);
        idx += 1;
    }
    if let Some(history) = req.history.filter(|h: &&History| !h.is_empty()) {
        for turn in history.iter() {
            match &turn.user {
                TurnUser::Results(r) => {
                    tool_results(&mut out, r, idx);
                    idx += r.len();
                }
                TurnUser::Text(s) => {
                    text(&mut out, s, "user", idx);
                    idx += 1;
                }
            }
            match &turn.assistant {
                TurnAssistant::Calls(c) => tool_calls(&mut out, c, idx),
                TurnAssistant::Text(s) => text(&mut out, s, "assistant", idx),
            }
            idx += 1;
        }
    }
    match req.msg {
        TurnUser::Results(r) => {
            tool_results(&mut out, r, idx);
            idx += r.len();
        }
        TurnUser::Text(s) => {
            text(&mut out, s, "user", idx);
            idx += 1;
        }
    }
    if let Some(notice) = req.notice.filter(|n| !n.is_empty()) {
        text(&mut out, notice, "user", idx);
    }
    out
}

fn llm_tools(tools: Option<&[ToolDefinition]>) -> Vec<(String, OtelValue)> {
    let Some(tools) = tools.filter(|t| !t.is_empty()) else {
        return Vec::new();
    };
    tools
        .iter()
        .enumerate()
        .map(|(i, t)| {
            (
                format!("llm.tools.{i}.tool.json_schema"),
                pyfmt::json_dumps(&json!({"name": t.name, "description": t.description, "input_schema": t.parameters}))
                    .into(),
            )
        })
        .collect()
}

fn tool_call_dict(tc: &ToolCall) -> Value {
    json!({"id": tc.id, "name": tc.name, "parameters": tc.parameters})
}

fn llm_output(response: &LlmResponse) -> Vec<(String, OtelValue)> {
    let mut out: Vec<(String, OtelValue)> = Vec::new();
    if !response.tool_calls.is_empty() {
        let calls: Vec<Value> = response.tool_calls.iter().map(tool_call_dict).collect();
        let value = if response.text.is_empty() {
            Value::Array(calls)
        } else {
            json!({"text": response.text, "tool_calls": calls})
        };
        out.push(("output.value".into(), pyfmt::json_dumps(&value).into()));
        out.push(("output.mime_type".into(), MIME_JSON.to_string().into()));
    } else {
        out.push(("output.value".into(), response.text.clone().into()));
        out.push(("output.mime_type".into(), MIME_TEXT.to_string().into()));
    }
    let base = "llm.output_messages.0.message";
    if !response.text.is_empty() {
        out.push((format!("{base}.role"), "assistant".to_string().into()));
        out.push((format!("{base}.content"), response.text.clone().into()));
    }
    if !response.tool_calls.is_empty() {
        out.push((format!("{base}.role"), "assistant".to_string().into()));
        for (i, tc) in response.tool_calls.iter().enumerate() {
            let prefix = format!("{base}.tool_calls.{i}");
            out.push((format!("{prefix}.tool_call.id"), tc.id.clone().into()));
            out.push((format!("{prefix}.tool_call.function.name"), tc.name.clone().into()));
            out.push((
                format!("{prefix}.tool_call.function.arguments"),
                pyfmt::json_dumps(&tc.parameters).into(),
            ));
        }
    }
    out
}

fn token_usage(m: &LlmMetadata) -> Vec<(String, OtelValue)> {
    vec![
        ("llm.token_count.prompt".into(), m.input_tokens.into()),
        ("llm.token_count.completion".into(), m.output_tokens.into()),
        (
            "llm.token_count.total".into(),
            (m.input_tokens + m.output_tokens).into(),
        ),
    ]
}

/// Trace one inference. Like the Python tracer, an inference outside any
/// chain has no parent to hang from and is an error.
pub fn trace_llm(trace: LlmTrace<'_>) -> AppResult<()> {
    let Some(t) = current() else {
        return Ok(());
    };
    let Some(parent) = t.root.lock().expect("root lock").clone() else {
        return Err(AppError::kind(
            ErrorKind::TracerRootContext,
            "Root context is not set",
            500,
        ));
    };
    let mut attrs = t.metadata(None);
    let msg_payload = match trace.request.msg {
        TurnUser::Text(s) => Value::String(s.clone()),
        TurnUser::Results(r) => Value::Array(r.iter().map(tool_result_dict).collect()),
    };
    attrs.extend(io_attrs("input", &msg_payload));
    attrs.push(kind_attr("LLM"));
    match trace.model_name {
        Some(name) => {
            attrs.push(("llm.model_name".into(), name.to_string().into()));
            if let Some(p) = trace.llm_provider.and_then(oi_provider) {
                attrs.push(("llm.provider".into(), p.to_string().into()));
            }
        }
        None => attrs.push(("llm.model_name".into(), trace.model.to_string().into())),
    }
    attrs.push((
        "llm.invocation_parameters".into(),
        pyfmt::json_dumps_unicode(trace.invocation_params).into(),
    ));
    attrs.extend(input_messages(trace.request));
    attrs.extend(llm_tools(trace.request.tools));
    attrs.extend(llm_output(trace.response));
    attrs.extend(token_usage(&trace.response.metadata));
    finish(t.start("Async Inference".into(), Some(trace.start), Some(parent), attrs));
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn routes_projects() {
        assert_eq!(
            route_project("production", OperationType::Drift),
            Some(TracerProject::ProTerraformDrift)
        );
        assert_eq!(
            route_project("staging", OperationType::Generate),
            Some(TracerProject::PreTerraformDay2)
        );
        assert_eq!(
            route_project("development", OperationType::Import),
            Some(TracerProject::DevTerraformImport)
        );
    }

    #[test]
    fn chain_output_prefers_summary() {
        let r = ToolResult {
            name: "task_complete".into(),
            tool_call_id: "1".into(),
            success: true,
            result: json!({"status": "done", "summary": ""}),
            error_message: None,
        };
        // An empty summary is falsy: the whole result is traced.
        let payload = match &r.result {
            Value::Object(m) => ["summary", "explanation", "description"]
                .iter()
                .filter_map(|k| m.get(*k))
                .find(|v| truthy(v))
                .cloned()
                .unwrap_or_else(|| r.result.clone()),
            other => other.clone(),
        };
        assert_eq!(payload, r.result);
    }
}
