// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

//! The slice of Phoenix's prompt REST API the core uses (what the
//! `arize-phoenix-client` prompts resource called): read a prompt version by
//! tag or the latest one, create a version, tag a version.

use std::sync::LazyLock;
use std::time::Duration;

use percent_encoding::{AsciiSet, NON_ALPHANUMERIC, utf8_percent_encode};
use serde_json::{Value, json};

/// Characters left as-is when a path parameter is quoted.
const PATH_SAFE: &AsciiSet = &NON_ALPHANUMERIC.remove(b'-').remove(b'_').remove(b'.').remove(b'~');

static HTTP: LazyLock<reqwest::Client> = LazyLock::new(|| {
    reqwest::Client::builder()
        .connect_timeout(Duration::from_secs(10))
        .read_timeout(Duration::from_secs(30))
        .build()
        .expect("reqwest client")
});

/// Why a Phoenix call failed.
#[derive(Debug, Clone)]
pub enum PhoenixError {
    /// 404: the prompt (or the tag) does not exist.
    NotFound(String),
    /// Any other non-2xx answer, with httpx's `raise_for_status` text.
    Status(u16, String),
    /// Could not connect at all (refused, DNS, connect timeout).
    Connect(String),
    /// Any other transport failure.
    Transport(String),
    /// A body that is not what the API documents.
    Shape(String),
}

impl std::fmt::Display for PhoenixError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            PhoenixError::NotFound(m)
            | PhoenixError::Status(_, m)
            | PhoenixError::Connect(m)
            | PhoenixError::Transport(m)
            | PhoenixError::Shape(m) => f.write_str(m),
        }
    }
}

/// httpx's `raise_for_status` message.
fn status_message(status: reqwest::StatusCode, url: &str) -> String {
    let kind = match status.as_u16() {
        100..=199 => "Informational response",
        300..=399 => "Redirect response",
        400..=499 => "Client error",
        _ => "Server error",
    };
    format!(
        "{kind} '{} {}' for url '{url}'\nFor more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/{}",
        status.as_u16(),
        status.canonical_reason().unwrap_or(""),
        status.as_u16()
    )
}

/// Headers from `PHOENIX_CLIENT_HEADERS` (W3C baggage format) and
/// `PHOENIX_API_KEY`, the way the Phoenix client resolves them.
fn env_headers() -> Vec<(String, String)> {
    let mut headers: Vec<(String, String)> = Vec::new();
    if let Ok(raw) = std::env::var("PHOENIX_CLIENT_HEADERS") {
        for item in raw.split(',') {
            let item = item.trim();
            if item.is_empty() {
                continue;
            }
            let Some((name, value)) = item.split_once('=') else {
                tracing::warn!(
                    "Header format invalid! Header values in environment variables must be URL encoded: {item}"
                );
                continue;
            };
            let name = percent_encoding::percent_decode_str(name)
                .decode_utf8_lossy()
                .trim()
                .to_lowercase();
            let value = percent_encoding::percent_decode_str(value)
                .decode_utf8_lossy()
                .trim()
                .to_string();
            headers.retain(|(k, _)| k != &name);
            headers.push((name, value));
        }
    }
    if let Ok(key) = std::env::var("PHOENIX_API_KEY")
        && !key.is_empty()
        && !headers.iter().any(|(k, _)| k.eq_ignore_ascii_case("authorization"))
    {
        headers.push(("Authorization".into(), format!("Bearer {key}")));
    }
    headers
}

#[derive(Clone)]
pub struct PhoenixClient {
    base_url: String,
}

impl PhoenixClient {
    pub fn new(base_url: &str) -> Self {
        let base = if base_url.ends_with('/') {
            base_url.to_string()
        } else {
            format!("{base_url}/")
        };
        Self { base_url: base }
    }

    fn url(&self, path: &str) -> String {
        format!("{}{}", self.base_url, path)
    }

    fn quote(s: &str) -> String {
        utf8_percent_encode(s, PATH_SAFE).to_string()
    }

    async fn send(&self, req: reqwest::RequestBuilder, url: &str) -> Result<Value, PhoenixError> {
        let mut req = req;
        for (k, v) in env_headers() {
            req = req.header(k, v);
        }
        let resp = req.send().await.map_err(|e| {
            if e.is_connect() || (e.is_timeout() && !e.is_body()) {
                PhoenixError::Connect(e.to_string())
            } else {
                PhoenixError::Transport(e.to_string())
            }
        })?;
        let status = resp.status();
        if !status.is_success() {
            return Err(if status.as_u16() == 404 {
                PhoenixError::NotFound(status_message(status, url))
            } else {
                PhoenixError::Status(status.as_u16(), status_message(status, url))
            });
        }
        resp.json::<Value>()
            .await
            .map_err(|e| PhoenixError::Transport(e.to_string()))
    }

    /// The version `tag` points at, or the latest one without a tag: the
    /// `data` object of the response.
    pub async fn get_prompt(&self, identifier: &str, tag: Option<&str>) -> Result<Value, PhoenixError> {
        let path = match tag {
            Some(t) => format!("v1/prompts/{}/tags/{}", Self::quote(identifier), Self::quote(t)),
            None => format!("v1/prompts/{}/latest", Self::quote(identifier)),
        };
        let url = self.url(&path);
        let body = self.send(HTTP.get(&url), &url).await?;
        body.get("data")
            .cloned()
            .ok_or_else(|| PhoenixError::Shape(format!("no data in response from {url}")))
    }

    /// Create a version for the prompt `name` (and the prompt itself if it
    /// does not exist); the created version's `data`.
    pub async fn create_prompt(
        &self,
        name: &str,
        description: Option<&str>,
        version: Value,
    ) -> Result<Value, PhoenixError> {
        let mut prompt = serde_json::Map::new();
        prompt.insert("name".into(), json!(name));
        if let Some(d) = description.filter(|d| !d.is_empty()) {
            prompt.insert("description".into(), json!(d));
        }
        let url = self.url("v1/prompts");
        let body = self
            .send(
                HTTP.post(&url).json(&json!({"prompt": prompt, "version": version})),
                &url,
            )
            .await?;
        body.get("data")
            .cloned()
            .ok_or_else(|| PhoenixError::Shape(format!("no data in response from {url}")))
    }

    pub async fn tag_version(&self, version_id: &str, tag: &str) -> Result<(), PhoenixError> {
        let url = self.url(&format!("v1/prompt_versions/{}/tags", Self::quote(version_id)));
        match self.send(HTTP.post(&url).json(&json!({"name": tag})), &url).await {
            Ok(_) => Ok(()),
            // A 204 has no JSON body.
            Err(PhoenixError::Transport(m)) if m.contains("EOF") || m.contains("decoding") => Ok(()),
            Err(e) => Err(e),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn httpx_status_text() {
        assert_eq!(
            status_message(reqwest::StatusCode::INTERNAL_SERVER_ERROR, "http://p/v1/x"),
            "Server error '500 Internal Server Error' for url 'http://p/v1/x'\nFor more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/500"
        );
    }
}
