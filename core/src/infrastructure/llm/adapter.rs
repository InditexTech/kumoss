// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

//! `LlmProvider` over the LiteLLM router in the sidecar.
//!
//! The conversation is laid out in OpenAI chat format here, exactly as the
//! in-process adapter did, and only the router call itself crosses to the
//! sidecar.

use std::time::SystemTime;

use async_trait::async_trait;
use serde_json::{Map, Value, json};

use crate::domain::dto::{LlmMetadata, LlmResponse, ToolCall, ToolDefinition, ToolResult};
use crate::domain::entities::{History, TurnAssistant, TurnUser};
use crate::domain::ports::{InferenceRequest, LlmProvider};
use crate::infrastructure::llm::sidecar::{SidecarClient, SidecarError};
use crate::infrastructure::telemetry;
use crate::shared::error::{AppError, AppResult, ErrorKind};
use crate::shared::pyfmt;

pub struct SidecarLlm {
    model: String,
    temperature: f64,
    max_tokens: i64,
    timeout: f64,
    client: SidecarClient,
}

impl SidecarLlm {
    pub fn new(model: &str, temperature: f64, max_tokens: i64, timeout: f64, client: SidecarClient) -> Self {
        Self {
            model: model.to_string(),
            temperature,
            max_tokens,
            timeout,
            client,
        }
    }

    fn format_tools(tools: &[ToolDefinition]) -> Value {
        Value::Array(
            tools
                .iter()
                .map(|t| {
                    json!({
                        "type": "function",
                        "function": {
                            "name": t.name,
                            "description": t.description,
                            "parameters": t.parameters,
                        }
                    })
                })
                .collect(),
        )
    }

    /// Content MUST be a string: provider converters (e.g. Anthropic)
    /// silently drop non-string content.
    fn format_tool_results(results: &[ToolResult], out: &mut Vec<Value>) {
        for r in results {
            let mut payload = Map::new();
            if r.success {
                payload.insert("success".into(), Value::Bool(true));
                payload.insert("result".into(), r.result.clone());
            } else {
                payload.insert("success".into(), Value::Bool(false));
                payload.insert(
                    "error".into(),
                    r.error_message.clone().map(Value::String).unwrap_or(Value::Null),
                );
            }
            out.push(json!({
                "role": "tool",
                "tool_call_id": r.tool_call_id,
                "content": pyfmt::json_dumps_unicode(&Value::Object(payload)),
            }));
        }
    }

    fn format_tool_calls(calls: &[ToolCall]) -> Value {
        Value::Array(
            calls
                .iter()
                .map(|c| {
                    json!({
                        "id": c.id,
                        "type": "function",
                        "function": {
                            "name": c.name,
                            "arguments": pyfmt::json_dumps(&c.parameters),
                        }
                    })
                })
                .collect(),
        )
    }

    fn format_history(history: Option<&History>, last: &TurnUser) -> Vec<Value> {
        let mut out = Vec::new();
        if let Some(history) = history {
            for turn in history.iter() {
                match &turn.user {
                    TurnUser::Results(results) => Self::format_tool_results(results, &mut out),
                    TurnUser::Text(text) => out.push(json!({"role": "user", "content": text})),
                }
                match &turn.assistant {
                    TurnAssistant::Calls(calls) if !calls.is_empty() => {
                        out.push(json!({"role": "assistant", "tool_calls": Self::format_tool_calls(calls)}));
                    }
                    TurnAssistant::Text(text) if !text.is_empty() => {
                        out.push(json!({"role": "assistant", "content": text}));
                    }
                    _ => {}
                }
            }
        }
        match last {
            TurnUser::Results(results) => Self::format_tool_results(results, &mut out),
            TurnUser::Text(text) => out.push(json!({"role": "user", "content": text})),
        }
        out
    }

    fn map_stop_reason(reason: Option<&str>) -> Option<String> {
        match reason? {
            "stop" => Some("end_turn".into()),
            "length" => Some("max_tokens".into()),
            "content_filter" => Some("content_filter".into()),
            "tool_calls" => Some("tool_use".into()),
            _ => None,
        }
    }
}

#[async_trait]
impl LlmProvider for SidecarLlm {
    fn model(&self) -> &str {
        &self.model
    }

    async fn inference(&self, request: InferenceRequest<'_>) -> AppResult<LlmResponse> {
        let start = SystemTime::now();
        let tools = request.tools.filter(|t| !t.is_empty());
        if tools.is_some() && request.thinking {
            return Err(AppError::kind(
                ErrorKind::InferenceCallThinkingTool,
                "Inference cannot be invoked with tools and thinking enabled.",
                400,
            ));
        }

        let mut messages = Self::format_history(request.history, request.msg);
        if let Some(notice) = request.notice.filter(|n| !n.is_empty()) {
            messages.push(json!({"role": "user", "content": notice}));
        }
        if let Some(system) = request.system_prompt.filter(|s| !s.is_empty()) {
            messages.insert(0, json!({"role": "system", "content": system}));
        }

        let mut kwargs = Map::new();
        kwargs.insert("model".into(), json!(self.model));
        kwargs.insert("messages".into(), Value::Array(messages));
        kwargs.insert("max_tokens".into(), json!(self.max_tokens));
        kwargs.insert(
            "temperature".into(),
            json!(if request.thinking { 1.0 } else { self.temperature }),
        );
        kwargs.insert("num_retries".into(), json!(3));
        kwargs.insert("timeout".into(), json!(self.timeout));
        if let Some(tools) = tools {
            kwargs.insert("tools".into(), Self::format_tools(tools));
            kwargs.insert("tool_choice".into(), json!("auto"));
        }
        if request.thinking {
            kwargs.insert("reasoning_effort".into(), json!("low"));
        }
        let kwargs = Value::Object(kwargs);

        let completion = match self.client.complete(&kwargs).await {
            Ok(c) => c,
            Err(err) => {
                let (code, detail) = match &err {
                    SidecarError::Transport(m) => (502, m.clone()),
                    SidecarError::Problem {
                        status,
                        upstream_status,
                        detail,
                    } if *status == 502 => (upstream_status.unwrap_or(502), detail.clone()),
                    SidecarError::Problem { status, detail, .. } => {
                        tracing::error!("LLM sidecar error {status}: {detail}");
                        return Err(AppError::internal(format!(
                            "LLM sidecar answered HTTP {status}: {detail}"
                        )));
                    }
                };
                tracing::error!("LiteLLM API error: {detail}");
                return Err(AppError::kind(
                    ErrorKind::InferenceCallApi,
                    format!("Inference call to {} failed.", self.model),
                    code,
                ));
            }
        };

        let mut tool_calls = Vec::new();
        for tc in &completion.tool_calls {
            let parameters: Value = serde_json::from_str(&tc.arguments)
                .map_err(|e| AppError::internal(format!("tool call arguments are not JSON: {e}")))?;
            tool_calls.push(ToolCall {
                id: tc.id.clone().unwrap_or_default(),
                name: tc.name.clone().unwrap_or_default(),
                parameters,
            });
        }
        let response = LlmResponse {
            text: completion.text.clone(),
            metadata: LlmMetadata {
                finish_reason: Self::map_stop_reason(completion.finish_reason.as_deref()),
                model: completion.model.clone().unwrap_or_default(),
                input_tokens: completion.prompt_tokens,
                output_tokens: completion.completion_tokens,
            },
            tool_calls,
            thinking: if request.thinking {
                completion.reasoning_content.clone()
            } else {
                None
            },
        };

        telemetry::trace_llm(telemetry::LlmTrace {
            start,
            model: &self.model,
            model_name: completion.model_name.as_deref(),
            llm_provider: completion.llm_provider.as_deref(),
            invocation_params: &kwargs,
            response: &response,
            request: &request,
        })?;
        Ok(response)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn history_layout_matches_python_adapter() {
        let mut h = History::new();
        h.append_text("first", "answer");
        h.append_turn(
            TurnUser::Text("go".into()),
            TurnAssistant::Calls(vec![ToolCall {
                id: "c1".into(),
                name: "read_file".into(),
                parameters: json!({"target_file": "é.tf"}),
            }]),
        );
        let last = TurnUser::Results(vec![ToolResult {
            name: "read_file".into(),
            tool_call_id: "c1".into(),
            success: true,
            result: json!({"content": "é"}),
            error_message: None,
        }]);
        let msgs = SidecarLlm::format_history(Some(&h), &last);
        assert_eq!(
            Value::Array(msgs),
            json!([
                {"role": "user", "content": "first"},
                {"role": "assistant", "content": "answer"},
                {"role": "user", "content": "go"},
                {"role": "assistant", "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "read_file", "arguments": "{\"target_file\": \"\\u00e9.tf\"}"}}]},
                {"role": "tool", "tool_call_id": "c1", "content": "{\"success\": true, \"result\": {\"content\": \"é\"}}"}
            ])
        );
    }

    #[test]
    fn stop_reasons() {
        assert_eq!(
            SidecarLlm::map_stop_reason(Some("tool_calls")).as_deref(),
            Some("tool_use")
        );
        assert_eq!(SidecarLlm::map_stop_reason(Some("stop")).as_deref(), Some("end_turn"));
        assert_eq!(SidecarLlm::map_stop_reason(Some("weird")), None);
        assert_eq!(SidecarLlm::map_stop_reason(None), None);
    }
}
