// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

//! Shared HTTP plumbing for the microservice contracts under
//! `contracts/openapi/`: bearer auth, per-call timeouts, and the RFC 7807
//! `Problem` body every error response carries.

use std::sync::LazyLock;
use std::time::Duration;

use serde_json::Value;

use crate::shared::pyfmt::repr_str;

/// One process-wide client; per-call timeouts are set on each request.
pub static HTTP: LazyLock<reqwest::Client> =
    LazyLock::new(|| reqwest::Client::builder().build().expect("reqwest client"));

/// Why a contract call produced no response.
#[derive(Debug)]
pub enum CallError {
    Timeout(String),
    Request(String),
}

/// A contract response: status plus the raw body.
#[derive(Debug, Clone)]
pub struct ContractResponse {
    pub status: u16,
    pub body: Vec<u8>,
}

impl ContractResponse {
    pub fn json(&self) -> Result<Value, String> {
        serde_json::from_slice(&self.body).map_err(|e| e.to_string())
    }
}

fn classify(e: reqwest::Error) -> CallError {
    if e.is_timeout() {
        CallError::Timeout(e.to_string())
    } else {
        CallError::Request(e.to_string())
    }
}

/// `{base_url}{path}` with a bearer token, the way the generated clients
/// built every request.
pub async fn call(
    method: reqwest::Method,
    base_url: &str,
    token: &str,
    timeout: f64,
    path: &str,
    body: Option<&Value>,
) -> Result<ContractResponse, CallError> {
    let url = format!("{}{}", base_url.trim_end_matches('/'), path);
    let mut req = HTTP
        .request(method, &url)
        .timeout(Duration::from_secs_f64(timeout))
        .header("Authorization", format!("Bearer {token}"));
    if let Some(b) = body {
        req = req
            .header("Content-Type", "application/json")
            .body(crate::shared::pyfmt::json_dumps(b));
    }
    let resp = req.send().await.map_err(classify)?;
    let status = resp.status().as_u16();
    let bytes = resp.bytes().await.map_err(classify)?;
    Ok(ContractResponse {
        status,
        body: bytes.to_vec(),
    })
}

/// An RFC 7807 problem body.
#[derive(Debug, Clone)]
pub struct Problem {
    pub title: String,
    pub status: i64,
    pub type_: String,
    pub detail: Option<String>,
    pub instance: Option<String>,
}

impl Problem {
    /// `Problem.from_dict`: `type`, `title` and `status` are required.
    pub fn from_value(v: &Value) -> Result<Self, String> {
        let obj = v
            .as_object()
            .ok_or_else(|| "problem body is not an object".to_string())?;
        let text = |k: &str| obj.get(k).and_then(Value::as_str).map(str::to_string);
        Ok(Self {
            type_: text("type").ok_or_else(|| "KeyError('type')".to_string())?,
            title: text("title").ok_or_else(|| "KeyError('title')".to_string())?,
            status: obj
                .get("status")
                .and_then(Value::as_i64)
                .ok_or_else(|| "KeyError('status')".to_string())?,
            detail: text("detail"),
            instance: text("instance"),
        })
    }

    /// The attrs repr the Python client printed in its error messages.
    pub fn py_repr(&self) -> String {
        let opt = |o: &Option<String>| match o {
            Some(s) => repr_str(s),
            None => "<Unset>".to_string(),
        };
        format!(
            "Problem(title={}, status={}, type_={}, detail={}, instance={}, additional_properties={{}})",
            repr_str(&self.title),
            self.status,
            repr_str(&self.type_),
            opt(&self.detail),
            opt(&self.instance)
        )
    }
}

/// What the generated client returned for a non-success status: a parsed
/// Problem for documented error codes, or `None`.
pub fn unexpected_repr(resp: &ContractResponse, problem_statuses: &[u16]) -> String {
    if problem_statuses.contains(&resp.status) {
        match resp.json().and_then(|v| Problem::from_value(&v)) {
            Ok(p) => p.py_repr(),
            Err(_) => format!("<unparseable {} response>", resp.status),
        }
    } else {
        "None".to_string()
    }
}
