// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

//! Client of the LLM sidecar (`services/llm`, `contracts/openapi/llm.v1.yaml`).
//!
//! The sidecar owns LiteLLM (the router behind every inference and the
//! `web_search` engines) and the headless Chromium page reads; the core
//! keeps everything around those calls.

use std::time::Duration;

use serde::Deserialize;
use serde_json::Value;

use crate::domain::value_objects::SearchResult;
use crate::infrastructure::external::contract::HTTP;
use crate::shared::config::SystemConfig;

/// One raw completion, as LiteLLM returned it.
#[derive(Debug, Clone, Deserialize)]
pub struct Completion {
    #[serde(default)]
    pub text: String,
    #[serde(default)]
    pub finish_reason: Option<String>,
    #[serde(default)]
    pub model: Option<String>,
    #[serde(default)]
    pub prompt_tokens: i64,
    #[serde(default)]
    pub completion_tokens: i64,
    #[serde(default)]
    pub tool_calls: Vec<RawToolCall>,
    #[serde(default)]
    pub reasoning_content: Option<String>,
    /// `litellm.get_llm_provider(model)`, for tracing; null when unresolvable.
    #[serde(default)]
    pub model_name: Option<String>,
    #[serde(default)]
    pub llm_provider: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct RawToolCall {
    #[serde(default)]
    pub id: Option<String>,
    #[serde(default)]
    pub name: Option<String>,
    pub arguments: String,
}

/// Why a sidecar call failed.
#[derive(Debug, Clone)]
pub enum SidecarError {
    /// The sidecar could not be reached or did not answer in time.
    Transport(String),
    /// A problem response: HTTP status, `detail`, and for completions the
    /// upstream provider's `status_code`.
    Problem {
        status: u16,
        detail: String,
        upstream_status: Option<u16>,
    },
}

#[derive(Clone)]
pub struct SidecarClient {
    cfg: &'static SystemConfig,
}

impl SidecarClient {
    pub fn new(cfg: &'static SystemConfig) -> Self {
        Self { cfg }
    }

    async fn post(&self, path: &str, body: &Value) -> Result<Value, SidecarError> {
        let svc = &self.cfg.services.llm;
        let url = format!("{}{}", svc.endpoint.trim_end_matches('/'), path);
        let resp = HTTP
            .post(&url)
            .timeout(Duration::from_secs_f64(svc.timeout))
            .header("Authorization", format!("Bearer {}", svc.token()))
            .header("Content-Type", "application/json")
            .body(serde_json::to_vec(body).map_err(|e| SidecarError::Transport(e.to_string()))?)
            .send()
            .await
            .map_err(|e| SidecarError::Transport(e.to_string()))?;
        let status = resp.status().as_u16();
        let bytes = resp.bytes().await.map_err(|e| SidecarError::Transport(e.to_string()))?;
        let parsed: Value = serde_json::from_slice(&bytes).unwrap_or(Value::Null);
        if status == 200 {
            return Ok(parsed);
        }
        Err(SidecarError::Problem {
            status,
            detail: parsed
                .get("detail")
                .and_then(Value::as_str)
                .map(str::to_string)
                .unwrap_or_else(|| String::from_utf8_lossy(&bytes).into_owned()),
            upstream_status: parsed
                .get("status_code")
                .and_then(Value::as_u64)
                .and_then(|s| u16::try_from(s).ok()),
        })
    }

    /// `router.acompletion(**kwargs, drop_params=True)`.
    pub async fn complete(&self, kwargs: &Value) -> Result<Completion, SidecarError> {
        let v = self.post("/v1/completions", kwargs).await?;
        serde_json::from_value(v).map_err(|e| SidecarError::Transport(format!("invalid completion payload: {e}")))
    }

    /// `litellm.asearch` plus one page read per hit.
    pub async fn search(&self, query: &str) -> Result<Vec<SearchResult>, SidecarError> {
        let v = self.post("/v1/search", &serde_json::json!({"query": query})).await?;
        let results = v.get("results").cloned().unwrap_or(Value::Array(Vec::new()));
        serde_json::from_value(results).map_err(|e| SidecarError::Transport(format!("invalid search payload: {e}")))
    }
}
