// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

//! Terraform Registry client used by the `terraform_docs` tool.
//!
//! A resource page is two calls away: `/v1/providers/<ns>/<name>[/<version>]`
//! pins the version and lists every documentation page of it, and
//! `/v2/provider-docs/<id>` returns the page as markdown. The page index of
//! a large provider is over a megabyte, so the index of every version read
//! is kept in-process (LRU, 16 entries).
//!
//! A provider, version or type the registry does not know is
//! `TerraformDocsNotFound` (the agent can fix it by asking differently); an
//! unreachable or misbehaving registry is `TerraformRegistry`.

use std::sync::{LazyLock, Mutex};
use std::time::Duration;

use indexmap::IndexMap;
use regex::Regex;
use serde_json::Value;

use crate::domain::value_objects::TerraformDoc;
use crate::shared::error::{AppError, AppResult, ErrorKind};

const REGISTRY_URL: &str = "https://registry.terraform.io";
const DEFAULT_HOST: &str = "registry.terraform.io";
const DEFAULT_NAMESPACE: &str = "hashicorp";
const INDEX_CACHE_SIZE: usize = 16;

static IMPORT_HEADING: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"(?mi)^##\s+Import\b.*$").unwrap());
static NEXT_SECTION: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"(?m)^##\s").unwrap());

type DocIndex = Vec<Value>;
/// (namespace, name, version) of one provider release.
type ProviderVersion = (String, String, String);

/// Provider release -> that version's documentation page index.
static DOC_INDEXES: LazyLock<Mutex<IndexMap<ProviderVersion, DocIndex>>> =
    LazyLock::new(|| Mutex::new(IndexMap::new()));

static HTTP: LazyLock<reqwest::Client> = LazyLock::new(|| {
    reqwest::Client::builder()
        .timeout(Duration::from_secs(30))
        .redirect(reqwest::redirect::Policy::limited(20))
        .build()
        .expect("reqwest client")
});

fn not_found(message: String) -> AppError {
    AppError::kind(ErrorKind::TerraformDocsNotFound, message, 404)
}

fn registry_error(message: &str, code: u16) -> AppError {
    AppError::kind(ErrorKind::TerraformRegistry, message, code)
}

#[derive(Clone, Default)]
pub struct TerraformRegistryClient {
    base_url: String,
}

impl TerraformRegistryClient {
    /// Cut before a page reaches the summarizer; aws_instance is ~50k.
    pub const MAX_DOC_CHARS: usize = 60000;

    pub fn new() -> Self {
        Self {
            base_url: REGISTRY_URL.into(),
        }
    }

    #[cfg(test)]
    pub fn with_base_url(base_url: &str) -> Self {
        Self {
            base_url: base_url.into(),
        }
    }

    /// The page of `resource_type` in `provider` at `version` (exact, or
    /// empty for the latest).
    pub async fn fetch(
        &self,
        provider: &str,
        resource_type: &str,
        version: Option<&str>,
        data_source: bool,
    ) -> AppResult<TerraformDoc> {
        let (namespace, name) = Self::split_source(provider)?;
        let resource_type = crate::shared::pyfmt::strip(resource_type).to_string();
        let (exact, index) = self.doc_index(&namespace, &name, version).await?;
        let category = if data_source { "data-sources" } else { "resources" };
        let Some(entry) = Self::find_page(&index, category, &name, &resource_type) else {
            return Err(not_found(format!(
                "{namespace}/{name} {exact} documents no {} named '{resource_type}'.",
                if data_source { "data source" } else { "resource" }
            )));
        };
        let id = crate::shared::pyfmt::str_value(entry.get("id").unwrap_or(&Value::Null));
        let page = self.get_json(&format!("/v2/provider-docs/{id}")).await?;
        let content = page
            .pointer("/data/attributes/content")
            .and_then(Value::as_str)
            .ok_or_else(|| registry_error(&format!("the registry returned no content for {resource_type}"), 502))?;
        let slug = crate::shared::pyfmt::str_value(entry.get("slug").unwrap_or(&Value::Null));
        Ok(TerraformDoc {
            source: format!("{namespace}/{name}"),
            version: exact.clone(),
            resource_type,
            url: format!("{REGISTRY_URL}/providers/{namespace}/{name}/{exact}/docs/{category}/{slug}"),
            content: Self::strip_frontmatter(content),
        })
    }

    /// The page's `## Import` section, heading included; `None` if absent.
    pub fn import_section(content: &str) -> Option<String> {
        let heading = IMPORT_HEADING.find(content)?;
        let end = NEXT_SECTION
            .find_at(content, heading.end())
            .map(|m| m.start())
            .unwrap_or(content.len());
        Some(crate::shared::pyfmt::strip(&content[heading.start()..end]).to_string())
    }

    /// `<namespace>/<name>` out of a provider source address: a bare name
    /// (meaning `hashicorp/<name>`), `<ns>/<name>` or
    /// `registry.terraform.io/<ns>/<name>`.
    pub fn split_source(provider: &str) -> AppResult<(String, String)> {
        let lowered = crate::shared::pyfmt::strip(provider).to_lowercase();
        let mut parts: Vec<String> = lowered
            .split('/')
            .filter(|p| !p.is_empty())
            .map(str::to_string)
            .collect();
        if parts.len() == 3 && parts[0] == DEFAULT_HOST {
            parts.remove(0);
        }
        if parts.len() == 1 {
            parts.insert(0, DEFAULT_NAMESPACE.into());
        }
        if parts.len() != 2 {
            return Err(AppError::kind(
                ErrorKind::TerraformDocsNotFound,
                format!(
                    "'{provider}' is not a Terraform Registry provider source; expected '<namespace>/<name>', e.g. 'hashicorp/aws'."
                ),
                400,
            ));
        }
        Ok((parts[0].clone(), parts[1].clone()))
    }

    async fn doc_index(&self, namespace: &str, name: &str, version: Option<&str>) -> AppResult<(String, DocIndex)> {
        let mut version = crate::shared::pyfmt::strip(version.unwrap_or("")).to_string();
        if let Some(v) = version.strip_prefix('v') {
            version = v.to_string();
        }
        if version.to_lowercase() == "latest" {
            version.clear();
        }
        let body = if !version.is_empty() {
            let key = (namespace.to_string(), name.to_string(), version.clone());
            {
                let mut cache = DOC_INDEXES.lock().expect("doc index lock");
                if let Some(index) = cache.shift_remove(&key) {
                    cache.insert(key, index.clone());
                    return Ok((version, index));
                }
            }
            self.get_json(&format!("/v1/providers/{namespace}/{name}/{version}"))
                .await?
        } else {
            self.get_json(&format!("/v1/providers/{namespace}/{name}")).await?
        };
        let exact = match body.get("version") {
            Some(v) if !v.is_null() && v != "" => crate::shared::pyfmt::str_value(v),
            _ => version.clone(),
        };
        let index: DocIndex = body.get("docs").and_then(Value::as_array).cloned().unwrap_or_default();
        let mut cache = DOC_INDEXES.lock().expect("doc index lock");
        let key = (namespace.to_string(), name.to_string(), exact.clone());
        // Re-assigning a key keeps its place, like a dict assignment.
        match cache.get_mut(&key) {
            Some(slot) => *slot = index.clone(),
            None => {
                cache.insert(key, index.clone());
            }
        }
        while cache.len() > INDEX_CACHE_SIZE {
            cache.shift_remove_index(0);
        }
        Ok((exact, index))
    }

    /// The HCL page of `resource_type`, whose slug drops the type prefix
    /// (usually the provider name, but `google-beta` documents `google_*`,
    /// so the first underscore-separated word is tried next).
    fn find_page<'a>(index: &'a [Value], category: &str, name: &str, resource_type: &str) -> Option<&'a Value> {
        let slugs = [
            resource_type
                .strip_prefix(&format!("{name}_"))
                .unwrap_or(resource_type)
                .to_string(),
            resource_type
                .split_once('_')
                .map(|(_, rest)| rest.to_string())
                .unwrap_or_else(|| resource_type.to_string()),
            resource_type.to_string(),
        ];
        let pages: Vec<&Value> = index
            .iter()
            .filter(|p| {
                p.get("category").and_then(Value::as_str) == Some(category)
                    && p.get("language").map(|l| l == "hcl").unwrap_or(true)
            })
            .collect();
        for slug in &slugs {
            for page in &pages {
                if page.get("slug").and_then(Value::as_str) == Some(slug.as_str()) {
                    return Some(page);
                }
            }
        }
        None
    }

    fn strip_frontmatter(content: &str) -> String {
        if content.starts_with("---")
            && let Some(end) = content[3..].find("\n---")
        {
            let end = end + 3;
            return content[end + "\n---".len()..]
                .trim_start_matches(crate::shared::pyfmt::is_space)
                .to_string();
        }
        content.to_string()
    }

    async fn get_json(&self, path: &str) -> AppResult<Value> {
        let resp = HTTP.get(format!("{}{path}", self.base_url)).send().await.map_err(|e| {
            if e.is_timeout() {
                registry_error("the Terraform Registry timed out", 504)
            } else {
                registry_error("the Terraform Registry is unreachable", 502)
            }
        })?;
        let status = resp.status().as_u16();
        if status == 404 {
            return Err(not_found(format!(
                "The Terraform Registry has no {}.",
                path.strip_prefix("/v1/providers/").unwrap_or(path)
            )));
        }
        if status != 200 {
            return Err(registry_error(
                &format!("the Terraform Registry answered HTTP {status}"),
                502,
            ));
        }
        resp.json::<Value>()
            .await
            .map_err(|_| registry_error("the Terraform Registry returned invalid JSON", 502))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn source_forms() {
        assert_eq!(
            TerraformRegistryClient::split_source("aws").unwrap(),
            ("hashicorp".into(), "aws".into())
        );
        assert_eq!(
            TerraformRegistryClient::split_source("registry.terraform.io/Hashicorp/AzureRM").unwrap(),
            ("hashicorp".into(), "azurerm".into())
        );
        assert!(TerraformRegistryClient::split_source("a/b/c/d").is_err());
    }

    #[test]
    fn import_section_extraction() {
        let doc = "# x\n\n## Argument Reference\nargs\n\n## Import\n\nterraform import a.b id\n\n## Timeouts\nt";
        assert_eq!(
            TerraformRegistryClient::import_section(doc).as_deref(),
            Some("## Import\n\nterraform import a.b id")
        );
        assert_eq!(TerraformRegistryClient::import_section("no import"), None);
    }

    #[test]
    fn frontmatter_and_slugs() {
        assert_eq!(
            TerraformRegistryClient::strip_frontmatter("---\ntitle: x\n---\n\n# Body"),
            "# Body"
        );
        let index = vec![
            json!({"category": "resources", "slug": "instance", "id": "1"}),
            json!({"category": "resources", "slug": "compute_instance", "language": "hcl", "id": "2"}),
        ];
        assert_eq!(
            TerraformRegistryClient::find_page(&index, "resources", "aws", "aws_instance").unwrap()["id"],
            "1"
        );
        assert_eq!(
            TerraformRegistryClient::find_page(&index, "resources", "google-beta", "google_compute_instance").unwrap()
                ["id"],
            "2"
        );
    }

    #[tokio::test]
    async fn fetches_through_two_calls() {
        use wiremock::matchers::{method, path};
        use wiremock::{Mock, MockServer, ResponseTemplate};
        let server = MockServer::start().await;
        Mock::given(method("GET"))
            .and(path("/v1/providers/hashicorp/aws"))
            .respond_with(ResponseTemplate::new(200).set_body_json(json!({
                "version": "9.9.9",
                "docs": [{"category": "resources", "slug": "s3_bucket", "id": "42", "language": "hcl"}]
            })))
            .mount(&server)
            .await;
        Mock::given(method("GET"))
            .and(path("/v2/provider-docs/42"))
            .respond_with(
                ResponseTemplate::new(200)
                    .set_body_json(json!({"data": {"attributes": {"content": "---\nx\n---\n# S3"}}})),
            )
            .mount(&server)
            .await;
        let client = TerraformRegistryClient::with_base_url(&server.uri());
        let doc = client.fetch("aws", "aws_s3_bucket", None, false).await.unwrap();
        assert_eq!(doc.version, "9.9.9");
        assert_eq!(doc.content, "# S3");
        assert_eq!(
            doc.url,
            "https://registry.terraform.io/providers/hashicorp/aws/9.9.9/docs/resources/s3_bucket"
        );
        let missing = client.fetch("aws", "aws_nope", None, false).await.unwrap_err();
        assert_eq!(
            missing.message,
            "hashicorp/aws 9.9.9 documents no resource named 'aws_nope'."
        );
    }
}
