// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

//! Reads guideline/resource/compliance prompts from Phoenix's prompt
//! registry. Not cached: the latest version of a tag is fetched at runtime,
//! so an operator's edit applies to the next round.

use serde_json::Value;

use crate::infrastructure::templates::phoenix::{PhoenixClient, PhoenixError};
use crate::shared::error::{AppError, AppResult, ErrorKind};

#[derive(Clone)]
pub struct PromptFetcher {
    client: PhoenixClient,
}

impl PromptFetcher {
    pub fn new(collector_url: &str) -> Self {
        Self {
            client: PhoenixClient::new(collector_url),
        }
    }

    /// The text of `{scope}-{type}-{prompt_name}` at `tag`.
    pub async fn fetch(&self, prompt_name: &str, scope: &str, kind: &str, tag: &str) -> AppResult<String> {
        let qualified = format!("{scope}-{kind}-{prompt_name}");
        let data = match self.client.get_prompt(&qualified, Some(tag)).await {
            Ok(d) => d,
            // The Phoenix client turned a 404 into ValueError, which the
            // fetcher never caught.
            Err(PhoenixError::NotFound(_)) => {
                return Err(AppError::internal(format!("Prompt not found: {qualified}")));
            }
            Err(PhoenixError::Status(code, msg)) => {
                return Err(AppError::kind(
                    ErrorKind::PhoenixPromptFetch,
                    format!("prompt_name={qualified}. {msg}"),
                    code,
                ));
            }
            Err(e) => {
                return Err(AppError::kind(
                    ErrorKind::PhoenixPromptFetch,
                    format!("prompt_name={qualified}. {e}"),
                    500,
                ));
            }
        };
        if data.pointer("/template/type").and_then(Value::as_str) != Some("chat") {
            return Err(AppError::internal(format!("prompt {qualified} is not a chat template")));
        }
        data.pointer("/template/messages/0/content/0/text")
            .and_then(Value::as_str)
            .map(str::to_string)
            .ok_or_else(|| {
                AppError::kind(
                    ErrorKind::PhoenixPromptFetch,
                    format!("error retrieving prompt from Phoenix API. name={qualified}"),
                    502,
                )
            })
    }
}
