// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

//! Pull-request REST APIs of the supported git providers. The personal
//! access token is the same one `git push` authenticates with.

use std::sync::LazyLock;
use std::time::Duration;

use percent_encoding::{NON_ALPHANUMERIC, utf8_percent_encode};
use serde_json::{Value, json};

use crate::domain::dto::PullRequestDto;
use crate::shared::config::SystemConfig;
use crate::shared::constants::GitProviderName;
use crate::shared::error::{AppError, AppResult};

const ADO_API_VERSION: &str = "7.1-preview";

static HTTP: LazyLock<reqwest::Client> = LazyLock::new(|| {
    reqwest::Client::builder()
        .timeout(Duration::from_secs(20))
        // httpx does not follow redirects by default: a 3xx is an error.
        .redirect(reqwest::redirect::Policy::none())
        .build()
        .expect("reqwest client")
});

#[derive(Clone)]
pub struct GitProvider {
    kind: GitProviderName,
    cfg: &'static SystemConfig,
}

/// `raise_for_status` + parse, mapping failures like the Python providers:
/// an HTTP error carries the response body and status, a timeout is a 504.
async fn send(req: reqwest::RequestBuilder, timeout_message: &str) -> AppResult<Value> {
    let resp = req.send().await.map_err(|e| {
        if e.is_timeout() {
            AppError::new(timeout_message, 504)
        } else {
            AppError::internal(e.to_string())
        }
    })?;
    let status = resp.status();
    let body = resp.text().await.map_err(|e| {
        if e.is_timeout() {
            AppError::new(timeout_message, 504)
        } else {
            AppError::internal(e.to_string())
        }
    })?;
    if !status.is_success() {
        return Err(AppError::new(body, status.as_u16()));
    }
    if body.is_empty() {
        return Ok(Value::Null);
    }
    serde_json::from_str(&body).map_err(|e| AppError::internal(e.to_string()))
}

fn field<'a>(v: &'a Value, path: &str) -> AppResult<&'a Value> {
    v.pointer(path)
        .ok_or_else(|| AppError::missing_key(path.rsplit('/').next().unwrap_or(path)))
}

impl GitProvider {
    pub fn new(kind: GitProviderName, cfg: &'static SystemConfig) -> Self {
        Self { kind, cfg }
    }

    pub async fn create_pr(
        &self,
        repository_url: &str,
        head: &str,
        base: &str,
        title: &str,
        description: &str,
    ) -> AppResult<PullRequestDto> {
        match self.kind {
            GitProviderName::Github => self.github_create(repository_url, head, base, title, description).await,
            GitProviderName::AzureDevops => self.ado_create(repository_url, head, base, title, description).await,
            GitProviderName::Gitlab => self.gitlab_create(repository_url, head, base, title, description).await,
        }
    }

    pub async fn complete_pr(&self, repository_url: &str, id: i64) -> AppResult<()> {
        match self.kind {
            GitProviderName::Github => self.github_complete(repository_url, id).await,
            GitProviderName::AzureDevops => self.ado_complete(repository_url, id).await,
            GitProviderName::Gitlab => self.gitlab_complete(repository_url, id).await,
        }
    }

    /// Lowercase, then drop the first eight characters when `https://`
    /// appears anywhere — exactly what the Python parsers did.
    fn strip_scheme(url: &str) -> String {
        let lowered = url.to_lowercase();
        if lowered.contains("https://") {
            crate::shared::pyfmt::skip_chars(&lowered, "https://".len()).to_string()
        } else {
            lowered
        }
    }

    // --- GitHub -----------------------------------------------------------------------

    fn github_request(&self, method: reqwest::Method, url: &str) -> reqwest::RequestBuilder {
        HTTP.request(method, url)
            .header("Accept", "application/vnd.github+json")
            .header("X-GitHub-Api-Version", "2022-11-28")
            .basic_auth(self.cfg.git.pat_user(), Some(self.cfg.git.pat_token()))
    }

    fn github_parse(repository_url: &str) -> AppResult<(String, String)> {
        let url = Self::strip_scheme(repository_url);
        let parts: Vec<&str> = url.split('/').collect();
        if parts.len() < 3 || parts[0] != "github.com" {
            return Err(AppError::new(format!("Malformed repository URL '{url}'"), 400));
        }
        let repo = parts[2].trim_end_matches('/');
        Ok((
            parts[1].to_string(),
            repo.strip_suffix(".git").unwrap_or(repo).to_string(),
        ))
    }

    async fn github_create(
        &self,
        repository_url: &str,
        head: &str,
        base: &str,
        title: &str,
        description: &str,
    ) -> AppResult<PullRequestDto> {
        let (owner, repo) = Self::github_parse(repository_url)?;
        let body = json!({"title": title, "head": head, "base": base, "body": description});
        let resp = send(
            self.github_request(
                reqwest::Method::POST,
                &format!("https://api.github.com/repos/{owner}/{repo}/pulls"),
            )
            .body(crate::shared::pyfmt::json_dumps(&body)),
            "PR creation timeout",
        )
        .await?;
        Ok(PullRequestDto {
            id: field(&resp, "/number")?.as_i64().unwrap_or(0),
            url: crate::shared::pyfmt::str_value(field(&resp, "/html_url")?),
            status: crate::shared::pyfmt::str_value(field(&resp, "/state")?),
        })
    }

    async fn github_complete(&self, repository_url: &str, id: i64) -> AppResult<()> {
        let (owner, repo) = Self::github_parse(repository_url)?;
        let mut i = 0;
        loop {
            let pr = send(
                self.github_request(
                    reqwest::Method::GET,
                    &format!("https://api.github.com/repos/{owner}/{repo}/pulls/{id}"),
                ),
                "Complete PR timeout",
            )
            .await?;
            match field(&pr, "/mergeable")? {
                Value::Bool(false) => return Err(AppError::new(format!("Pull Request {id} cannot be merged."), 400)),
                Value::Bool(true) => break,
                _ => {}
            }
            if i >= self.cfg.orchestration.pull_request_readiness_seconds {
                return Err(AppError::new(
                    format!("Pull Request {id} readiness polling exhausted."),
                    504,
                ));
            }
            i += 1;
            tokio::time::sleep(Duration::from_secs(1)).await;
        }
        send(
            self.github_request(
                reqwest::Method::PUT,
                &format!("https://api.github.com/repos/{owner}/{repo}/pulls/{id}/merge"),
            ),
            "Complete PR timeout",
        )
        .await?;
        Ok(())
    }

    // --- Azure DevOps -------------------------------------------------------------------

    fn ado_request(&self, method: reqwest::Method, url: &str) -> reqwest::RequestBuilder {
        // ADO accepts any value in the username slot; the PAT goes in the password slot.
        HTTP.request(method, url)
            .header("Accept", "application/json")
            .header("Content-Type", "application/json")
            .basic_auth("", Some(self.cfg.git.pat_token()))
    }

    fn ado_parse(repository_url: &str) -> AppResult<(String, String, String)> {
        let url = Self::strip_scheme(repository_url);
        let url = url.trim_end_matches('/');
        let parts: Vec<&str> = url.split('/').collect();
        if parts.len() != 5 || !parts[0].contains("dev.azure.com") || parts[3] != "_git" {
            return Err(AppError::new(format!("Malformed repository URL '{url}'"), 400));
        }
        Ok((
            parts[1].to_string(),
            parts[2].to_string(),
            parts[4].strip_suffix(".git").unwrap_or(parts[4]).to_string(),
        ))
    }

    async fn ado_create(
        &self,
        repository_url: &str,
        head: &str,
        base: &str,
        title: &str,
        description: &str,
    ) -> AppResult<PullRequestDto> {
        let (org, project, repo) = Self::ado_parse(repository_url)?;
        let body = json!({
            "sourceRefName": format!("refs/heads/{head}"),
            "targetRefName": format!("refs/heads/{base}"),
            "title": title,
            "description": description,
        });
        let resp = send(
            self.ado_request(
                reqwest::Method::POST,
                &format!("https://dev.azure.com/{org}/{project}/_apis/git/repositories/{repo}/pullrequests?api-version={ADO_API_VERSION}"),
            )
            .body(crate::shared::pyfmt::json_dumps(&body)),
            "PR creation timeout",
        )
        .await?;
        let pr_id = field(&resp, "/pullRequestId")?.clone();
        Ok(PullRequestDto {
            id: pr_id.as_i64().unwrap_or(0),
            url: format!(
                "https://dev.azure.com/{org}/{project}/_git/{repo}/pullrequest/{}",
                crate::shared::pyfmt::str_value(&pr_id)
            ),
            status: crate::shared::pyfmt::str_value(field(&resp, "/status")?),
        })
    }

    async fn ado_complete(&self, repository_url: &str, id: i64) -> AppResult<()> {
        let (org, project, repo) = Self::ado_parse(repository_url)?;
        let conn = send(
            self.ado_request(
                reqwest::Method::GET,
                &format!("https://dev.azure.com/{org}/_apis/connectionData?api-version={ADO_API_VERSION}"),
            ),
            "Complete PR timeout",
        )
        .await?;
        let user_id = field(&conn, "/authenticatedUser/id")?.clone();
        let user = crate::shared::pyfmt::str_value(&user_id);
        let base = format!("https://dev.azure.com/{org}/{project}/_apis/git/repositories/{repo}/pullrequests/{id}");
        send(
            self.ado_request(
                reqwest::Method::PUT,
                &format!("{base}/reviewers/{user}?api-version={ADO_API_VERSION}"),
            )
            .body(crate::shared::pyfmt::json_dumps(&json!({"vote": 10, "id": user_id}))),
            "Complete PR timeout",
        )
        .await?;
        let pr = send(
            self.ado_request(reqwest::Method::GET, &format!("{base}?api-version={ADO_API_VERSION}")),
            "Complete PR timeout",
        )
        .await?;
        let commit_id = field(&pr, "/lastMergeSourceCommit/commitId")?.clone();
        send(
            self.ado_request(reqwest::Method::PATCH, &format!("{base}?api-version={ADO_API_VERSION}"))
                .body(crate::shared::pyfmt::json_dumps(
                    &json!({"status": "completed", "lastMergeSourceCommit": {"commitId": commit_id}}),
                )),
            "Complete PR timeout",
        )
        .await?;
        Ok(())
    }

    // --- GitLab ----------------------------------------------------------------------------

    fn gitlab_request(&self, method: reqwest::Method, url: &str) -> reqwest::RequestBuilder {
        HTTP.request(method, url)
            .header("PRIVATE-TOKEN", self.cfg.git.pat_token())
            .header("Accept", "application/json")
    }

    fn gitlab_project_id(repository_url: &str) -> AppResult<String> {
        let url = Self::strip_scheme(repository_url);
        let url = url.trim_end_matches('/');
        let parts: Vec<&str> = url.split('/').collect();
        if parts.len() != 3 || parts[0] != "gitlab.com" {
            return Err(AppError::new(format!("Malformed repository URL '{url}'"), 400));
        }
        let project = parts[2].strip_suffix(".git").unwrap_or(parts[2]);
        Ok(utf8_percent_encode(&format!("{}/{project}", parts[1]), &PY_QUOTE_NO_SAFE).to_string())
    }

    async fn gitlab_create(
        &self,
        repository_url: &str,
        head: &str,
        base: &str,
        title: &str,
        description: &str,
    ) -> AppResult<PullRequestDto> {
        let project_id = Self::gitlab_project_id(repository_url)?;
        let body = json!({"source_branch": head, "target_branch": base, "title": title, "description": description});
        let resp = send(
            self.gitlab_request(
                reqwest::Method::POST,
                &format!("https://gitlab.com/api/v4/projects/{project_id}/merge_requests"),
            )
            .body(crate::shared::pyfmt::json_dumps(&body)),
            "PR creation timeout",
        )
        .await?;
        Ok(PullRequestDto {
            id: field(&resp, "/iid")?.as_i64().unwrap_or(0),
            url: crate::shared::pyfmt::str_value(field(&resp, "/web_url")?),
            status: crate::shared::pyfmt::str_value(field(&resp, "/state")?),
        })
    }

    async fn gitlab_complete(&self, repository_url: &str, id: i64) -> AppResult<()> {
        let project_id = Self::gitlab_project_id(repository_url)?;
        let base = format!("https://gitlab.com/api/v4/projects/{project_id}/merge_requests/{id}");
        send(
            self.gitlab_request(reqwest::Method::POST, &format!("{base}/approve")),
            "Complete PR timeout",
        )
        .await?;
        send(
            self.gitlab_request(reqwest::Method::PUT, &format!("{base}/merge")),
            "Complete PR timeout",
        )
        .await?;
        Ok(())
    }
}

/// `urllib.parse.quote(s, safe="")`: everything but `A-Za-z0-9_.-~` escaped.
const PY_QUOTE_NO_SAFE: percent_encoding::AsciiSet =
    NON_ALPHANUMERIC.remove(b'_').remove(b'.').remove(b'-').remove(b'~');

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn url_parsing() {
        assert_eq!(
            GitProvider::github_parse("https://GitHub.com/Org/Repo.git").unwrap(),
            ("org".into(), "repo".into())
        );
        assert_eq!(
            GitProvider::ado_parse("https://org@dev.azure.com/Org/Proj/_git/Repo/").unwrap(),
            ("org".into(), "proj".into(), "repo".into())
        );
        assert!(GitProvider::ado_parse("https://dev.azure.com/org/repo").is_err());
        assert_eq!(
            GitProvider::gitlab_project_id("https://gitlab.com/ns/proj.git").unwrap(),
            "ns%2Fproj"
        );
        let err = GitProvider::github_parse("https://gitlab.com/a/b").unwrap_err();
        assert_eq!(err.message, "Malformed repository URL 'gitlab.com/a/b'");
    }
}
