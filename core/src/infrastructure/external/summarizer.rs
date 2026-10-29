// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

//! Two-stage LLM reduction of the pages the `web_search` tool fetched.
//!
//! Stage 1 condenses every result independently and concurrently with the
//! small model; a summary is an extract, not a gist. Stage 2 ranks those
//! summaries against the query in a single cross-page inference. A page
//! whose summary fails keeps a truncated raw excerpt, an unusable ranking
//! falls back to every relevant summary in engine order, and any
//! summarizer-level error is left to the tool to swallow.

use std::sync::Arc;

use crate::domain::entities::TurnUser;
use crate::domain::ports::{InferenceRequest, LlmProvider};
use crate::domain::value_objects::{PageSummary, SearchResult};
use crate::shared::config::SystemConfig;
use crate::shared::error::{AppError, AppResult, ErrorKind};
use crate::shared::pyfmt;

const IRRELEVANT: &str = "IRRELEVANT";

/// Whether the small model judged this page useless for the query.
fn is_irrelevant(summary: &str) -> bool {
    pyfmt::strip(summary).to_uppercase() == IRRELEVANT
}

fn page_prompt(query: &str, result: &SearchResult) -> String {
    format!(
        "Query: {query}\n\nPage title: {}\nPage url: {}\n\nPage content:\n{}",
        result.title, result.url, result.content
    )
}

fn select_prompt(query: &str, listing: &str) -> String {
    format!("Query: {query}\n\nSummaries:\n\n{listing}")
}

/// Overlap-free `SELECT: ...` ids picked out of the verdict: best-first
/// unique zero-based ids bounded to valid positions. An empty list is the
/// model's own `SELECT: none`; `None` is the absence of a usable verdict.
pub fn parse_selection(verdict: &str, total: usize) -> Option<Vec<usize>> {
    let marker = "SELECT:";
    let cut = verdict.find(marker)?;
    let answer = pyfmt::strip(&verdict[cut + marker.len()..]);
    if answer.to_lowercase().starts_with("none") {
        return Some(Vec::new());
    }
    let mut parsed: Vec<usize> = Vec::new();
    for token in answer.split(',') {
        let token = pyfmt::strip(token);
        let first = token.split(pyfmt::is_space).find(|s| !s.is_empty()).unwrap_or("");
        if !first.is_empty()
            && first.chars().all(|c| c.is_ascii_digit())
            && let Ok(n) = first.parse::<usize>()
            && n < total
            && !parsed.contains(&n)
        {
            parsed.push(n);
        }
    }
    if parsed.is_empty() { None } else { Some(parsed) }
}

#[derive(Clone)]
pub struct SearchResultsSummarizer {
    llm: Arc<dyn LlmProvider>,
    summarize_system: String,
    select_system: String,
    cfg: &'static SystemConfig,
}

impl SearchResultsSummarizer {
    pub fn new(
        llm: Arc<dyn LlmProvider>,
        summarize_system: String,
        select_system: String,
        cfg: &'static SystemConfig,
    ) -> Self {
        Self {
            llm,
            summarize_system,
            select_system,
            cfg,
        }
    }

    pub fn irrelevant_marker() -> &'static str {
        IRRELEVANT
    }

    async fn infer(&self, system_prompt: &str, msg: &str) -> AppResult<String> {
        let user = TurnUser::Text(msg.to_string());
        let mut req = InferenceRequest::new(&user);
        req.system_prompt = Some(system_prompt);
        Ok(self.llm.inference(req).await?.text)
    }

    /// Summaries, then a cross-page ranking: `(selected, discarded)`, where
    /// `selected` holds at most `summarize_top` summaries in relevance order.
    /// An empty `selected` is a verdict (nothing answers the query).
    pub async fn best(&self, query: &str, results: &[SearchResult]) -> AppResult<(Vec<PageSummary>, Vec<PageSummary>)> {
        let summaries = self.summarize(query, results).await;
        let irrelevant: Vec<PageSummary> = summaries
            .iter()
            .filter(|s| is_irrelevant(&s.summary))
            .cloned()
            .collect();
        let relevant: Vec<PageSummary> = summaries
            .iter()
            .filter(|s| !is_irrelevant(&s.summary))
            .cloned()
            .collect();
        if relevant.is_empty() {
            tracing::info!("Every page found for query '{query}' summarized as irrelevant; nothing to rank.");
            return Ok((Vec::new(), summaries));
        }
        let ranked_ids = match self.select(query, &relevant, results.len()).await {
            Ok(r) => r,
            Err(e) => {
                tracing::warn!("Falling back to the engine order: {}", e.message);
                return Ok((relevant, irrelevant));
            }
        };
        let Some(ranked_ids) = ranked_ids else {
            tracing::warn!("No usable page ranking for query '{query}'; returning every summary unranked.");
            return Ok((relevant, irrelevant));
        };
        if ranked_ids.is_empty() {
            tracing::info!("No page found for query '{query}' answers it.");
            return Ok((Vec::new(), summaries));
        }
        let ranked: Vec<PageSummary> = ranked_ids
            .iter()
            .filter_map(|i| relevant.iter().find(|s| s.index == *i).cloned())
            .collect();
        let unranked: Vec<PageSummary> = relevant
            .iter()
            .filter(|s| !ranked_ids.contains(&s.index))
            .cloned()
            .collect();
        let top_n = usize::try_from(self.cfg.web_search.summarize_top).unwrap_or(1);
        let top: Vec<PageSummary> = ranked.iter().take(top_n).cloned().collect();
        let mut rest: Vec<PageSummary> = ranked.into_iter().skip(top_n).collect();
        rest.extend(unranked);
        rest.extend(irrelevant);
        Ok((top, rest))
    }

    /// One small-LLM summary per page, all in flight at once. A page whose
    /// inference fails keeps a truncated copy of its content.
    pub async fn summarize(&self, query: &str, results: &[SearchResult]) -> Vec<PageSummary> {
        let cap = usize::try_from(self.cfg.web_search.summarize_max_chars).unwrap_or(4000);
        let futures = results.iter().enumerate().map(|(i, r)| async move {
            let outcome = self.infer(&self.summarize_system, &page_prompt(query, r)).await;
            (i, r, outcome)
        });
        let mut out = Vec::new();
        for (i, r, outcome) in futures::future::join_all(futures).await {
            match outcome {
                Ok(summary) => out.push(PageSummary {
                    index: i,
                    result: r.clone(),
                    summary: pyfmt::take_chars(&summary, cap).to_string(),
                }),
                Err(e) => {
                    tracing::warn!(
                        "Keeping a raw excerpt after a failed page summary: the summary inference for '{}' failed ({})",
                        r.url,
                        e.message
                    );
                    out.push(PageSummary {
                        index: i,
                        result: r.clone(),
                        summary: pyfmt::take_chars(&r.content, cap).to_string(),
                    });
                }
            }
        }
        out
    }

    /// One page reduced to what bears on `query`, with no ranking. `None`
    /// means the page holds nothing for the query.
    pub async fn condense(&self, query: &str, result: &SearchResult) -> AppResult<Option<String>> {
        let summary = self.summarize(query, std::slice::from_ref(result)).await.remove(0);
        Ok(if is_irrelevant(&summary.summary) {
            None
        } else {
            Some(summary.summary)
        })
    }

    async fn select(&self, query: &str, summaries: &[PageSummary], total: usize) -> AppResult<Option<Vec<usize>>> {
        let listing = summaries
            .iter()
            .map(|s| {
                format!(
                    "id={}\ntitle: {}\nurl: {}\nsummary: {}",
                    s.index, s.result.title, s.result.url, s.summary
                )
            })
            .collect::<Vec<_>>()
            .join("\n\n");
        let verdict = self
            .infer(&self.select_system, &select_prompt(query, &listing))
            .await
            .map_err(|_| {
                AppError::kind(
                    ErrorKind::PageSelection,
                    format!("the cross-page selection for '{query}' failed"),
                    502,
                )
            })?;
        Ok(parse_selection(&verdict, total))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn selection_parsing() {
        assert_eq!(parse_selection("blah SELECT: 2, 0, 2, 9", 3), Some(vec![2, 0]));
        assert_eq!(parse_selection("SELECT: none", 3), Some(vec![]));
        assert_eq!(parse_selection("no marker", 3), None);
        assert_eq!(parse_selection("SELECT: 7", 3), None);
        assert_eq!(parse_selection("SELECT: 1 (best), 0", 3), Some(vec![1, 0]));
    }

    #[test]
    fn irrelevant_marker() {
        assert!(is_irrelevant("  irrelevant \n"));
        assert!(!is_irrelevant("irrelevant stuff"));
    }
}
