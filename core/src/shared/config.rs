// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

//! System-wide configuration loaded from a YAML file.
//!
//! Single source of truth for every deployment-tunable knob in the core.
//! Resolved at startup from the path in `KUMOSS_CONFIG`; if unset or
//! missing, the defaults defined here apply (so the OSS distribution boots
//! without any config file).
//!
//! Secrets never live in this file. Fields named `*_env` carry the name of
//! an environment variable that holds the actual secret; the value is read
//! at use time.
//!
//! Validation follows the pydantic models the Python core used: lax scalar
//! coercion, YAML nulls rejected rather than defaulted, unknown keys
//! ignored. The `llm` model list and the `web_search` provider are
//! validated by the LLM sidecar, which owns LiteLLM.

use std::path::PathBuf;
use std::sync::LazyLock;

use regex::Regex;
use serde_json::{Map, Value};
use url::Url;

use crate::shared::constants::{ENVIRONMENTS, GitProviderName, ObjectStorageProvider};

#[derive(Debug)]
pub struct ConfigError(pub String);

impl std::fmt::Display for ConfigError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.0)
    }
}

impl std::error::Error for ConfigError {}

fn env(name: &str, default: &str) -> String {
    if name.is_empty() {
        return default.to_string();
    }
    std::env::var(name).unwrap_or_else(|_| default.to_string())
}

// --- lax field readers ---------------------------------------------------

/// Collects pydantic-style validation errors while a section is read.
struct Reader<'a> {
    errors: &'a mut Vec<String>,
    loc: String,
    data: Map<String, Value>,
}

fn type_name(v: &Value) -> &'static str {
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

impl<'a> Reader<'a> {
    fn new(errors: &'a mut Vec<String>, loc: &str, value: Option<&Value>, model: &str) -> Option<Self> {
        match value {
            None => Some(Self {
                errors,
                loc: loc.to_string(),
                data: Map::new(),
            }),
            Some(Value::Object(map)) => Some(Self {
                errors,
                loc: loc.to_string(),
                data: map.clone(),
            }),
            Some(other) => {
                errors.push(format!(
                    "{loc}\n  Input should be a valid dictionary or instance of {model} [input_type={}]",
                    type_name(other)
                ));
                None
            }
        }
    }

    fn at(&self, key: &str) -> String {
        if self.loc.is_empty() {
            key.to_string()
        } else {
            format!("{}.{}", self.loc, key)
        }
    }

    fn fail(&mut self, key: &str, msg: String) {
        let loc = self.at(key);
        self.errors.push(format!("{loc}\n  {msg}"));
    }

    fn raw(&self, key: &str) -> Option<Value> {
        self.data.get(key).cloned()
    }

    fn string(&mut self, key: &str, default: &str) -> String {
        match self.raw(key) {
            None => default.to_string(),
            Some(Value::String(s)) => s,
            Some(other) => {
                self.fail(
                    key,
                    format!("Input should be a valid string [input_type={}]", type_name(&other)),
                );
                default.to_string()
            }
        }
    }

    fn float(&mut self, key: &str, default: f64) -> f64 {
        match self.raw(key) {
            None => default,
            Some(Value::Number(n)) => n.as_f64().unwrap_or(default),
            Some(Value::Bool(b)) => {
                if b {
                    1.0
                } else {
                    0.0
                }
            }
            Some(Value::String(s)) => match crate::shared::pyfmt::strip(&s).parse::<f64>() {
                Ok(v) => v,
                Err(_) => {
                    self.fail(
                        key,
                        "Input should be a valid number, unable to parse string as a number".into(),
                    );
                    default
                }
            },
            Some(other) => {
                self.fail(
                    key,
                    format!("Input should be a valid number [input_type={}]", type_name(&other)),
                );
                default
            }
        }
    }

    fn int(&mut self, key: &str, default: i64) -> i64 {
        match self.raw(key) {
            None => default,
            Some(Value::Number(n)) => {
                if let Some(i) = n.as_i64() {
                    i
                } else if let Some(f) = n.as_f64() {
                    if f.fract() == 0.0 && f.is_finite() {
                        f as i64
                    } else {
                        self.fail(
                            key,
                            "Input should be a valid integer, got a number with a fractional part".into(),
                        );
                        default
                    }
                } else {
                    default
                }
            }
            Some(Value::Bool(b)) => i64::from(b),
            Some(Value::String(s)) => match crate::shared::pyfmt::strip(&s).parse::<i64>() {
                Ok(v) => v,
                Err(_) => {
                    self.fail(
                        key,
                        "Input should be a valid integer, unable to parse string as an integer".into(),
                    );
                    default
                }
            },
            Some(other) => {
                self.fail(
                    key,
                    format!("Input should be a valid integer [input_type={}]", type_name(&other)),
                );
                default
            }
        }
    }

    fn boolean(&mut self, key: &str, default: bool) -> bool {
        match self.raw(key) {
            None => default,
            Some(Value::Bool(b)) => b,
            Some(Value::Number(n)) => match n.as_f64() {
                Some(0.0) => false,
                Some(1.0) => true,
                _ => {
                    self.fail(key, "Input should be a valid boolean, unable to interpret input".into());
                    default
                }
            },
            Some(Value::String(s)) => match s.to_lowercase().as_str() {
                "0" | "off" | "f" | "false" | "n" | "no" => false,
                "1" | "on" | "t" | "true" | "y" | "yes" => true,
                _ => {
                    self.fail(key, "Input should be a valid boolean, unable to interpret input".into());
                    default
                }
            },
            Some(other) => {
                self.fail(
                    key,
                    format!("Input should be a valid boolean [input_type={}]", type_name(&other)),
                );
                default
            }
        }
    }

    fn string_list(&mut self, key: &str, default: Vec<String>) -> Vec<String> {
        match self.raw(key) {
            None => default,
            Some(Value::Array(items)) => {
                let mut out = Vec::new();
                for (i, item) in items.iter().enumerate() {
                    match item {
                        Value::String(s) => out.push(s.clone()),
                        other => self.fail(
                            &format!("{key}.{i}"),
                            format!("Input should be a valid string [input_type={}]", type_name(other)),
                        ),
                    }
                }
                out
            }
            Some(other) => {
                self.fail(
                    key,
                    format!("Input should be a valid list [input_type={}]", type_name(&other)),
                );
                default
            }
        }
    }

    fn check(&mut self, key: &str, ok: bool, msg: String) {
        if !ok {
            self.fail(key, msg);
        }
    }

    fn pattern(&mut self, key: &str, value: &str, pattern: &str) {
        let re = Regex::new(pattern).expect("static pattern");
        if !re.is_match(value) {
            self.fail(key, format!("String should match pattern '{pattern}'"));
        }
    }

    fn value_error(&mut self, msg: impl Into<String>) {
        let loc = self.loc.clone();
        self.errors.push(format!("{loc}\n  Value error, {}", msg.into()));
    }
}

// --- sections ---------------------------------------------------------------

/// OIDC issuer settings for authenticating requests to the core.
///
/// Blank `issuer_url` disables authentication entirely (dev default):
/// every request acts as a local developer identity holding the top role
/// of both groups. `audience` is an optional override for IdPs (e.g.
/// Auth0) that issue tokens for a dedicated API identifier; when blank,
/// `client_id` and `api://{client_id}` are accepted. A `{client_id}`
/// placeholder in `scope` is expanded at load time; when `scope` is left at
/// its default and the issuer is Entra ID, `api://{client_id}/.default` is
/// appended so the access token is issued for this app.
#[derive(Debug, Clone)]
pub struct OidcConfig {
    pub issuer_url: String,
    pub client_id: String,
    pub audience: String,
    pub scope: String,
    pub clock_skew_seconds: i64,
}

impl OidcConfig {
    pub const DEFAULT_OIDC_SCOPE: &'static str = "openid profile email";
    const ENTRA_HOST: &'static str = "login.microsoftonline.com";

    fn read(errors: &mut Vec<String>, value: Option<&Value>) -> Self {
        let mut cfg = OidcConfig {
            issuer_url: String::new(),
            client_id: String::new(),
            audience: String::new(),
            scope: Self::DEFAULT_OIDC_SCOPE.into(),
            clock_skew_seconds: 60,
        };
        let before = errors.len();
        let Some(mut r) = Reader::new(errors, "oidc", value, "OidcConfig") else {
            return cfg;
        };
        cfg.issuer_url = r.string("issuer_url", "");
        cfg.client_id = r.string("client_id", "");
        cfg.audience = r.string("audience", "");
        cfg.scope = r.string("scope", Self::DEFAULT_OIDC_SCOPE);
        cfg.clock_skew_seconds = r.int("clock_skew_seconds", 60);
        if r.errors.len() > before {
            return cfg;
        }
        if !cfg.issuer_url.is_empty() && cfg.client_id.is_empty() {
            r.value_error(
                "oidc.issuer_url is set but oidc.client_id is empty; set oidc.client_id (and optionally oidc.audience) in config.yaml.",
            );
            return cfg;
        }
        if cfg.scope == Self::DEFAULT_OIDC_SCOPE && url_hostname(&cfg.issuer_url).as_deref() == Some(Self::ENTRA_HOST) {
            cfg.scope = format!("{} api://{{client_id}}/.default", Self::DEFAULT_OIDC_SCOPE);
        }
        if cfg.scope.contains("{client_id}") {
            if cfg.client_id.is_empty() {
                r.value_error("oidc.scope references {client_id} but oidc.client_id is empty.");
                return cfg;
            }
            cfg.scope = cfg.scope.replace("{client_id}", &cfg.client_id);
        }
        cfg
    }
}

/// Bootstrap administrator: the user whose verified token email matches
/// `default_root_email` is elevated to the top role of both groups.
#[derive(Debug, Clone, Default)]
pub struct AdminConfig {
    pub default_root_email: String,
}

/// Web search backend used by the core's `web_search` tool.
///
/// The search itself runs in the LLM sidecar (LiteLLM search providers,
/// headless Chromium page reads); the core keeps the knobs that shape the
/// tool result: whether search is enabled at all and how much of it the
/// summarizer lets through.
#[derive(Debug, Clone)]
pub struct SearchConfig {
    pub provider: String,
    pub endpoint: String,
    pub timeout: f64,
    pub max_results: i64,
    pub max_page_chars: i64,
    pub summarize_top: i64,
    pub summarize_max_chars: i64,
}

impl SearchConfig {
    fn read(errors: &mut Vec<String>, value: Option<&Value>) -> Self {
        let mut cfg = SearchConfig {
            provider: "searxng".into(),
            endpoint: "http://localhost:8888".into(),
            timeout: 30.0,
            max_results: 5,
            max_page_chars: 6000,
            summarize_top: 1,
            summarize_max_chars: 4000,
        };
        let before = errors.len();
        let Some(mut r) = Reader::new(errors, "web_search", value, "SearchConfig") else {
            return cfg;
        };
        cfg.provider = r.string("provider", "searxng");
        cfg.endpoint = r.string("endpoint", "http://localhost:8888");
        cfg.timeout = r.float("timeout", 30.0);
        r.check("timeout", cfg.timeout > 0.0, "Input should be greater than 0".into());
        cfg.max_results = r.int("max_results", 5);
        r.check(
            "max_results",
            cfg.max_results >= 1,
            "Input should be greater than or equal to 1".into(),
        );
        r.check(
            "max_results",
            cfg.max_results <= 20,
            "Input should be less than or equal to 20".into(),
        );
        cfg.max_page_chars = r.int("max_page_chars", 6000);
        r.check(
            "max_page_chars",
            cfg.max_page_chars >= 500,
            "Input should be greater than or equal to 500".into(),
        );
        r.check(
            "max_page_chars",
            cfg.max_page_chars <= 20000,
            "Input should be less than or equal to 20000".into(),
        );
        cfg.summarize_top = r.int("summarize_top", 1);
        r.check(
            "summarize_top",
            cfg.summarize_top >= 1,
            "Input should be greater than or equal to 1".into(),
        );
        r.check(
            "summarize_top",
            cfg.summarize_top <= 10,
            "Input should be less than or equal to 10".into(),
        );
        cfg.summarize_max_chars = r.int("summarize_max_chars", 4000);
        r.check(
            "summarize_max_chars",
            cfg.summarize_max_chars >= 500,
            "Input should be greater than or equal to 500".into(),
        );
        r.check(
            "summarize_max_chars",
            cfg.summarize_max_chars <= 20000,
            "Input should be less than or equal to 20000".into(),
        );
        if r.errors.len() > before {
            return cfg;
        }
        if cfg.provider.is_empty() {
            if !cfg.endpoint.is_empty() {
                r.value_error(
                    "web_search.endpoint is set but web_search.provider is empty; set web_search.provider (e.g. searxng) or clear the endpoint to disable web search.",
                );
            }
            return cfg;
        }
        if cfg.provider == "searxng" && cfg.endpoint.is_empty() {
            r.value_error(
                "web_search.provider 'searxng' requires web_search.endpoint (the base URL of the SearXNG instance).",
            );
        }
        cfg
    }
}

/// LLM model selection. `model` handles complex tasks, `small_model` cheap
/// filler tasks; both are LiteLLM model strings resolved by the sidecar's
/// router. `temperature`, `max_output_tokens` and `timeout` apply to both.
#[derive(Debug, Clone)]
pub struct LlmConfig {
    pub model: String,
    pub small_model: String,
    pub temperature: f64,
    pub max_output_tokens: i64,
    pub timeout: f64,
}

impl LlmConfig {
    fn read(errors: &mut Vec<String>, value: Option<&Value>) -> Self {
        let mut cfg = LlmConfig {
            model: "anthropic/claude-sonnet-5".into(),
            small_model: "anthropic/claude-haiku-4-5".into(),
            temperature: 0.1,
            max_output_tokens: 32000,
            timeout: 600.0,
        };
        let Some(mut r) = Reader::new(errors, "llm", value, "LlmConfig") else {
            return cfg;
        };
        cfg.model = r.string("model", "anthropic/claude-sonnet-5");
        cfg.small_model = r.string("small_model", "anthropic/claude-haiku-4-5");
        cfg.temperature = r.float("temperature", 0.1);
        cfg.max_output_tokens = r.int("max_output_tokens", 32000);
        cfg.timeout = r.float("timeout", 600.0);
        r.check("timeout", cfg.timeout > 0.0, "Input should be greater than 0".into());
        match r.raw("model_list") {
            None | Some(Value::Array(_)) => {}
            Some(other) => r.fail(
                "model_list",
                format!("Input should be a valid list [input_type={}]", type_name(&other)),
            ),
        }
        cfg
    }
}

/// Outbound HTTP wiring shared by every microservice contract. `token_env`
/// names the env var holding the bearer token the core sends with every
/// call; `timeout` is the per-request budget in seconds.
#[derive(Debug, Clone)]
pub struct ServiceConfig {
    pub enabled: bool,
    pub endpoint: String,
    pub token_env: String,
    pub timeout: f64,
}

impl ServiceConfig {
    pub fn token(&self) -> String {
        env(&self.token_env, "")
    }

    fn read(errors: &mut Vec<String>, name: &str, value: Option<&Value>) -> Self {
        let mut cfg = ServiceConfig {
            enabled: false,
            endpoint: String::new(),
            token_env: String::new(),
            timeout: 30.0,
        };
        let loc = format!("services.{name}");
        let Some(mut r) = Reader::new(errors, &loc, value, "ServiceConfig") else {
            return cfg;
        };
        cfg.endpoint = r.string("endpoint", "");
        cfg.token_env = r.string("token_env", "");
        cfg.timeout = r.float("timeout", 30.0);
        cfg.enabled = r.boolean("enabled", false);
        cfg
    }
}

/// IaC service wiring plus its async-job polling knobs. Mandatory: no
/// `enabled` flag, `endpoint` and `token_env` are always required.
#[derive(Debug, Clone)]
pub struct IacServiceConfig {
    pub endpoint: String,
    pub token_env: String,
    pub timeout: f64,
    pub job_poll_interval: f64,
    pub job_timeout: f64,
}

impl IacServiceConfig {
    pub fn token(&self) -> String {
        env(&self.token_env, "")
    }

    fn read(errors: &mut Vec<String>, value: Option<&Value>) -> Self {
        let mut cfg = IacServiceConfig {
            endpoint: "http://iac:8082".into(),
            token_env: "KUMOSS_IAC_TOKEN".into(),
            timeout: 30.0,
            job_poll_interval: 5.0,
            job_timeout: 3600.0,
        };
        let before = errors.len();
        let Some(mut r) = Reader::new(errors, "services.iac", value, "IacServiceConfig") else {
            return cfg;
        };
        cfg.endpoint = r.string("endpoint", "http://iac:8082");
        cfg.token_env = r.string("token_env", "KUMOSS_IAC_TOKEN");
        cfg.timeout = r.float("timeout", 30.0);
        cfg.job_poll_interval = r.float("job_poll_interval", 5.0);
        cfg.job_timeout = r.float("job_timeout", 3600.0);
        if r.errors.len() > before {
            return cfg;
        }
        if cfg.endpoint.is_empty() {
            r.value_error(
                "services.iac.endpoint is empty; the IaC service is mandatory. Point it at an implementation of the iac contract.",
            );
        }
        cfg
    }
}

/// LLM sidecar wiring (`services/llm`): LiteLLM completions and the
/// `web_search` engine plus page reads. Mandatory, like the IaC service.
/// `timeout` bounds one sidecar call, which covers LiteLLM's own retries.
#[derive(Debug, Clone)]
pub struct LlmServiceConfig {
    pub endpoint: String,
    pub token_env: String,
    pub timeout: f64,
}

impl LlmServiceConfig {
    pub fn token(&self) -> String {
        env(&self.token_env, "")
    }

    fn read(errors: &mut Vec<String>, value: Option<&Value>) -> Self {
        let mut cfg = LlmServiceConfig {
            endpoint: "http://llm:8090".into(),
            token_env: "KUMOSS_LLM_TOKEN".into(),
            timeout: 2700.0,
        };
        let before = errors.len();
        let Some(mut r) = Reader::new(errors, "services.llm", value, "LlmServiceConfig") else {
            return cfg;
        };
        cfg.endpoint = r.string("endpoint", "http://llm:8090");
        cfg.token_env = r.string("token_env", "KUMOSS_LLM_TOKEN");
        cfg.timeout = r.float("timeout", 2700.0);
        r.check("timeout", cfg.timeout > 0.0, "Input should be greater than 0".into());
        if r.errors.len() > before {
            return cfg;
        }
        if cfg.endpoint.is_empty() {
            r.value_error(
                "services.llm.endpoint is empty; the LLM service is mandatory. Point it at an implementation of the llm contract.",
            );
        }
        cfg
    }
}

#[derive(Debug, Clone)]
pub struct ServicesConfig {
    pub notifications: ServiceConfig,
    pub mapping: ServiceConfig,
    pub authz: ServiceConfig,
    pub iac: IacServiceConfig,
    pub llm: LlmServiceConfig,
}

/// Iteration limits and batch sizes for the core's orchestration loops.
#[derive(Debug, Clone)]
pub struct OrchestrationConfig {
    pub max_drift_reports: i64,
    pub max_validation_iteration: i64,
    pub max_import_iteration: i64,
    pub max_tool_agent_executions: i64,
    pub max_session_events_iteration: i64,
    pub drift_group_operations: i64,
    pub pull_request_readiness_seconds: i64,
    pub enable_compliance_checker: bool,
    pub block_on_high_impact: bool,
}

/// Filesystem paths used by the core.
#[derive(Debug, Clone)]
pub struct PathsConfig {
    pub upload_folder: PathBuf,
    pub session_plan_filename: String,
    pub backend_override_filename: String,
}

/// Generic OTel telemetry knobs. `collector_url` is a base URL; the OTLP
/// endpoint is `{collector_url}v1/traces`.
#[derive(Debug, Clone)]
pub struct TelemetryConfig {
    pub collector_url: String,
    pub otel_attribute_count_limit: i64,
    pub otel_console_exporter: bool,
}

#[derive(Debug, Clone)]
pub struct HttpConfig {
    pub cors_origins: Vec<String>,
}

/// Credentials for `git push` against the remote hosting user repos.
#[derive(Debug, Clone)]
pub struct GitConfig {
    pub provider: GitProviderName,
    pub pat_user_env: String,
    pub pat_token_env: String,
    pub author_name: String,
    pub author_email: String,
}

impl GitConfig {
    pub fn pat_user(&self) -> String {
        env(&self.pat_user_env, "")
    }

    pub fn pat_token(&self) -> String {
        env(&self.pat_token_env, "")
    }
}

#[derive(Debug, Clone)]
pub struct DatabaseConfig {
    pub kumoss_database_url_env: String,
}

impl DatabaseConfig {
    pub fn kumoss_database_url(&self) -> String {
        env(&self.kumoss_database_url_env, "")
    }
}

/// Connection settings for the Redis session store / cache.
#[derive(Debug, Clone)]
pub struct RedisConfig {
    pub redis_url_env: String,
    pub default_url: String,
    pub max_connections: i64,
    pub socket_connect_timeout: f64,
    pub socket_timeout: f64,
    pub pool_timeout: f64,
}

impl RedisConfig {
    pub fn redis_url(&self) -> String {
        let v = env(&self.redis_url_env, "");
        if v.is_empty() { self.default_url.clone() } else { v }
    }
}

/// Object storage for generated artifacts (reports, plans, code changes)
/// and, in a second bucket of the same store, Terraform state.
#[derive(Debug, Clone)]
pub struct StorageConfig {
    pub provider: ObjectStorageProvider,
    pub bucket: String,
    pub terraform_state_bucket: String,
    pub terraform_state_filename: String,
    pub endpoint_url: String,
    pub public_endpoint_url: String,
    pub region: String,
    pub access_key_env: String,
    pub secret_key_env: String,
    pub account_key_env: String,
    pub connect_timeout: f64,
    pub read_timeout: f64,
    pub max_attempts: i64,
    pub presign_expiry_seconds: i64,
}

impl StorageConfig {
    pub fn access_key(&self) -> String {
        let default = if self.provider == ObjectStorageProvider::Rustfs {
            "rustfsadmin"
        } else {
            ""
        };
        env(&self.access_key_env, default)
    }

    pub fn secret_key(&self) -> String {
        let default = if self.provider == ObjectStorageProvider::Rustfs {
            "rustfsadmin"
        } else {
            ""
        };
        env(&self.secret_key_env, default)
    }

    pub fn account_key(&self) -> String {
        env(&self.account_key_env, "")
    }

    /// The Terraform state bucket, or "" when state is not managed.
    pub fn state_bucket(&self) -> String {
        crate::shared::pyfmt::strip(&self.terraform_state_bucket).to_string()
    }

    /// Account name derived from `endpoint_url` (STORAGE_ACCOUNT): either
    /// `https://<account>.blob.<domain>` or the emulator-style path form
    /// `http://<host>:<port>/<account>`.
    pub fn storage_account_name(&self) -> Result<String, ConfigError> {
        let host = url_hostname(&self.endpoint_url).unwrap_or_default();
        let labels: Vec<&str> = host.split('.').collect();
        if labels.len() >= 2 && labels[1] == "blob" {
            return Ok(labels[0].to_string());
        }
        let path = url_path(&self.endpoint_url);
        let path = path.trim_matches('/');
        if !path.is_empty() && !path.contains('/') {
            return Ok(path.to_string());
        }
        Err(ConfigError(format!(
            "storage.endpoint_url must be an account blob endpoint (https://<account>.blob.core.windows.net) when storage.provider is STORAGE_ACCOUNT; cannot derive an account name from '{}'.",
            self.endpoint_url
        )))
    }
}

/// `urlparse(url).hostname`: lowercased, `None` when absent.
pub fn url_hostname(raw: &str) -> Option<String> {
    let parsed = urlsplit(raw);
    parsed.hostname
}

fn url_path(raw: &str) -> String {
    urlsplit(raw).path
}

/// The pieces of `urllib.parse.urlparse` the core reads.
#[derive(Debug, Clone, Default)]
pub struct UrlParts {
    pub scheme: String,
    pub netloc: String,
    pub path: String,
    pub query: String,
    pub fragment: String,
    pub username: Option<String>,
    pub password: Option<String>,
    pub hostname: Option<String>,
}

/// `urllib.parse.urlsplit`, which never fails on malformed input the way
/// `url::Url` does, so the core reads the same pieces Python did.
pub fn urlsplit(raw: &str) -> UrlParts {
    let mut rest = raw;
    let mut parts = UrlParts::default();
    // scheme: letters, digits, + - . starting with a letter, followed by ':'
    if let Some(idx) = rest.find(':') {
        let candidate = &rest[..idx];
        if !candidate.is_empty()
            && candidate.chars().next().is_some_and(|c| c.is_ascii_alphabetic())
            && candidate
                .chars()
                .all(|c| c.is_ascii_alphanumeric() || matches!(c, '+' | '-' | '.'))
        {
            parts.scheme = candidate.to_lowercase();
            rest = &rest[idx + 1..];
        }
    }
    if let Some(after) = rest.strip_prefix("//") {
        let end = after.find(['/', '?', '#']).unwrap_or(after.len());
        parts.netloc = after[..end].to_string();
        rest = &after[end..];
    }
    if let Some(idx) = rest.find('#') {
        parts.fragment = rest[idx + 1..].to_string();
        rest = &rest[..idx];
    }
    if let Some(idx) = rest.find('?') {
        parts.query = rest[idx + 1..].to_string();
        rest = &rest[..idx];
    }
    parts.path = rest.to_string();
    if !parts.netloc.is_empty() {
        let (userinfo, hostport) = match parts.netloc.rfind('@') {
            Some(i) => (Some(&parts.netloc[..i]), &parts.netloc[i + 1..]),
            None => (None, parts.netloc.as_str()),
        };
        if let Some(info) = userinfo {
            match info.split_once(':') {
                Some((u, p)) => {
                    parts.username = Some(u.to_string());
                    parts.password = Some(p.to_string());
                }
                None => parts.username = Some(info.to_string()),
            }
        }
        let host = if let Some(stripped) = hostport.strip_prefix('[') {
            stripped.split(']').next().unwrap_or("").to_string()
        } else {
            hostport.split(':').next().unwrap_or("").to_string()
        };
        parts.hostname = if host.is_empty() {
            None
        } else {
            Some(host.to_lowercase())
        };
    }
    parts
}

/// The complete system configuration.
#[derive(Debug, Clone)]
pub struct SystemConfig {
    pub environment: String,
    pub oidc: OidcConfig,
    pub admin: AdminConfig,
    pub llm: LlmConfig,
    pub web_search: SearchConfig,
    pub services: ServicesConfig,
    pub orchestration: OrchestrationConfig,
    pub paths: PathsConfig,
    pub database: DatabaseConfig,
    pub redis: RedisConfig,
    pub storage: StorageConfig,
    pub telemetry: TelemetryConfig,
    pub http: HttpConfig,
    pub git: GitConfig,
}

fn coerce_enum<T: Copy>(
    r: &mut Reader<'_>,
    key: &str,
    default: T,
    type_label: &str,
    by_name: impl Fn(&str) -> Option<T>,
    by_value: impl Fn(&str) -> Option<T>,
    expected: String,
) -> T {
    match r.raw(key) {
        None => default,
        Some(Value::String(s)) => match by_name(&s).or_else(|| by_value(&s)) {
            Some(v) => v,
            None => {
                r.fail(key, format!("Value error, '{s}' is not a valid {type_label}"));
                default
            }
        },
        Some(other) => {
            let _ = other;
            r.fail(key, format!("Input should be {expected}"));
            default
        }
    }
}

impl SystemConfig {
    /// Build from a decoded YAML document, applying every validator.
    pub fn from_value(data: &Value) -> Result<Self, ConfigError> {
        let mut errors: Vec<String> = Vec::new();
        let root = match data {
            Value::Object(m) => m.clone(),
            other => {
                return Err(ConfigError(format!(
                    "1 validation error for SystemConfig\n  Input should be a valid dictionary or instance of SystemConfig [input_type={}]",
                    type_name(other)
                )));
            }
        };
        let get = |k: &str| root.get(k);

        // environment
        let environment = match get("environment") {
            None => "development".to_string(),
            Some(Value::String(s)) if ENVIRONMENTS.contains(&s.as_str()) => s.clone(),
            Some(_) => {
                errors.push("environment\n  Input should be 'development', 'staging' or 'production'".into());
                "development".into()
            }
        };

        let oidc = OidcConfig::read(&mut errors, get("oidc"));

        let admin = {
            let mut admin = AdminConfig::default();
            if let Some(mut r) = Reader::new(&mut errors, "admin", get("admin"), "AdminConfig") {
                admin.default_root_email = r.string("default_root_email", "");
            }
            admin
        };

        let llm = LlmConfig::read(&mut errors, get("llm"));
        let web_search = SearchConfig::read(&mut errors, get("web_search"));

        let services = {
            let default_services = || ServicesConfig {
                notifications: ServiceConfig {
                    enabled: false,
                    endpoint: String::new(),
                    token_env: String::new(),
                    timeout: 30.0,
                },
                mapping: ServiceConfig {
                    enabled: false,
                    endpoint: String::new(),
                    token_env: String::new(),
                    timeout: 30.0,
                },
                authz: ServiceConfig {
                    enabled: false,
                    endpoint: String::new(),
                    token_env: String::new(),
                    timeout: 30.0,
                },
                iac: IacServiceConfig {
                    endpoint: "http://iac:8082".into(),
                    token_env: "KUMOSS_IAC_TOKEN".into(),
                    timeout: 30.0,
                    job_poll_interval: 5.0,
                    job_timeout: 3600.0,
                },
                llm: LlmServiceConfig {
                    endpoint: "http://llm:8090".into(),
                    token_env: "KUMOSS_LLM_TOKEN".into(),
                    timeout: 2700.0,
                },
            };
            match get("services") {
                None => {
                    let mut s = default_services();
                    s.iac = IacServiceConfig::read(&mut errors, None);
                    s.llm = LlmServiceConfig::read(&mut errors, None);
                    s
                }
                Some(Value::Object(m)) => {
                    let m = m.clone();
                    ServicesConfig {
                        notifications: ServiceConfig::read(&mut errors, "notifications", m.get("notifications")),
                        mapping: ServiceConfig::read(&mut errors, "mapping", m.get("mapping")),
                        authz: ServiceConfig::read(&mut errors, "authz", m.get("authz")),
                        iac: IacServiceConfig::read(&mut errors, m.get("iac")),
                        llm: LlmServiceConfig::read(&mut errors, m.get("llm")),
                    }
                }
                Some(other) => {
                    errors.push(format!(
                        "services\n  Input should be a valid dictionary or instance of ServicesConfig [input_type={}]",
                        type_name(other)
                    ));
                    default_services()
                }
            }
        };

        let orchestration = {
            let mut o = OrchestrationConfig {
                max_drift_reports: 3,
                max_validation_iteration: 8,
                max_import_iteration: 5,
                max_tool_agent_executions: 40,
                max_session_events_iteration: 2160,
                drift_group_operations: 8,
                pull_request_readiness_seconds: 10,
                enable_compliance_checker: false,
                block_on_high_impact: false,
            };
            if let Some(mut r) = Reader::new(
                &mut errors,
                "orchestration",
                get("orchestration"),
                "OrchestrationConfig",
            ) {
                o.max_drift_reports = r.int("max_drift_reports", 3);
                o.max_validation_iteration = r.int("max_validation_iteration", 8);
                o.max_import_iteration = r.int("max_import_iteration", 5);
                o.max_tool_agent_executions = r.int("max_tool_agent_executions", 40);
                o.max_session_events_iteration = r.int("max_session_events_iteration", 2160);
                o.drift_group_operations = r.int("drift_group_operations", 8);
                o.pull_request_readiness_seconds = r.int("pull_request_readiness_seconds", 10);
                o.enable_compliance_checker = r.boolean("enable_compliance_checker", false);
                o.block_on_high_impact = r.boolean("block_on_high_impact", false);
            }
            o
        };

        let paths = {
            let mut p = PathsConfig {
                upload_folder: PathBuf::from("/workspaces"),
                session_plan_filename: "session.plan".into(),
                backend_override_filename: "backend_override.tf".into(),
            };
            if let Some(mut r) = Reader::new(&mut errors, "paths", get("paths"), "PathsConfig") {
                p.upload_folder = PathBuf::from(r.string("upload_folder", "/workspaces"));
                p.session_plan_filename = r.string("session_plan_filename", "session.plan");
                let plan = p.session_plan_filename.clone();
                r.pattern("session_plan_filename", &plan, r"^[A-Za-z0-9._-]{1,128}$");
                p.backend_override_filename = r.string("backend_override_filename", "backend_override.tf");
                let backend = p.backend_override_filename.clone();
                r.pattern(
                    "backend_override_filename",
                    &backend,
                    r"^[A-Za-z0-9._-]{1,128}_override\.tf$",
                );
            }
            p
        };

        let database = {
            let mut d = DatabaseConfig {
                kumoss_database_url_env: "KUMOSS_SQL_DATABASE_URL".into(),
            };
            let before = errors.len();
            if let Some(mut r) = Reader::new(&mut errors, "database", get("database"), "DatabaseConfig") {
                d.kumoss_database_url_env = r.string("kumoss_database_url_env", "KUMOSS_SQL_DATABASE_URL");
                if r.errors.len() == before && d.kumoss_database_url().is_empty() {
                    r.value_error("Missing env variable for kumoss database");
                }
            }
            d
        };

        let redis = {
            let mut c = RedisConfig {
                redis_url_env: "KUMOSS_REDIS_URL".into(),
                default_url: "redis://redis:6379/0".into(),
                max_connections: 20,
                socket_connect_timeout: 2.0,
                socket_timeout: 2.0,
                pool_timeout: 2.0,
            };
            if let Some(mut r) = Reader::new(&mut errors, "redis", get("redis"), "RedisConfig") {
                c.redis_url_env = r.string("redis_url_env", "KUMOSS_REDIS_URL");
                c.default_url = r.string("default_url", "redis://redis:6379/0");
                c.max_connections = r.int("max_connections", 20);
                c.socket_connect_timeout = r.float("socket_connect_timeout", 2.0);
                c.socket_timeout = r.float("socket_timeout", 2.0);
                c.pool_timeout = r.float("pool_timeout", 2.0);
            }
            c
        };

        let storage = {
            let mut s = StorageConfig {
                provider: ObjectStorageProvider::Rustfs,
                bucket: "kumoss-artifacts".into(),
                terraform_state_bucket: "kumoss-terraform-state".into(),
                terraform_state_filename: "terraform.tfstate".into(),
                endpoint_url: "http://object-storage:9000".into(),
                public_endpoint_url: "http://localhost:9000".into(),
                region: "us-east-1".into(),
                access_key_env: "RUSTFS_ACCESS_KEY".into(),
                secret_key_env: "RUSTFS_SECRET_KEY".into(),
                account_key_env: "STORAGE_ACCOUNT_KEY".into(),
                connect_timeout: 3.0,
                read_timeout: 10.0,
                max_attempts: 3,
                presign_expiry_seconds: 172_800,
            };
            let before = errors.len();
            if let Some(mut r) = Reader::new(&mut errors, "storage", get("storage"), "StorageConfig") {
                s.provider = coerce_enum(
                    &mut r,
                    "provider",
                    ObjectStorageProvider::Rustfs,
                    "ObjectStorageProvider",
                    ObjectStorageProvider::from_name,
                    ObjectStorageProvider::from_value,
                    ObjectStorageProvider::expected(),
                );
                s.bucket = r.string("bucket", "kumoss-artifacts");
                s.terraform_state_bucket = r.string("terraform_state_bucket", "kumoss-terraform-state");
                s.terraform_state_filename = r.string("terraform_state_filename", "terraform.tfstate");
                let state_file = s.terraform_state_filename.clone();
                r.pattern("terraform_state_filename", &state_file, r"^[A-Za-z0-9._-]{1,128}$");
                s.endpoint_url = r.string("endpoint_url", "http://object-storage:9000");
                s.public_endpoint_url = r.string("public_endpoint_url", "http://localhost:9000");
                s.region = r.string("region", "us-east-1");
                s.access_key_env = r.string("access_key_env", "RUSTFS_ACCESS_KEY");
                s.secret_key_env = r.string("secret_key_env", "RUSTFS_SECRET_KEY");
                s.account_key_env = r.string("account_key_env", "STORAGE_ACCOUNT_KEY");
                s.connect_timeout = r.float("connect_timeout", 3.0);
                s.read_timeout = r.float("read_timeout", 10.0);
                s.max_attempts = r.int("max_attempts", 3);
                s.presign_expiry_seconds = r.int("presign_expiry_seconds", 172_800);
                if r.errors.len() == before {
                    if s.provider == ObjectStorageProvider::StorageAccount {
                        if let Err(e) = s.storage_account_name() {
                            r.value_error(e.0);
                        } else if s.account_key().is_empty() {
                            r.value_error(format!(
                                "storage.provider STORAGE_ACCOUNT requires env var {}.",
                                s.account_key_env
                            ));
                        }
                    }
                    if !(108_000..=604_800).contains(&s.presign_expiry_seconds) {
                        r.value_error(format!(
                            "storage.presign_expiry_seconds must be between 108000 (30h, to outlive the cached session detail aggregate) and 604800 (the SigV4 7-day limit); got {}.",
                            s.presign_expiry_seconds
                        ));
                    }
                }
            }
            s
        };

        let telemetry = {
            let mut t = TelemetryConfig {
                collector_url: "http://phoenix:6006/".into(),
                otel_attribute_count_limit: 1024,
                otel_console_exporter: false,
            };
            if let Some(mut r) = Reader::new(&mut errors, "telemetry", get("telemetry"), "TelemetryConfig") {
                t.collector_url = r.string("collector_url", "http://phoenix:6006/");
                t.otel_attribute_count_limit = r.int("otel_attribute_count_limit", 1024);
                t.otel_console_exporter = r.boolean("otel_console_exporter", false);
            }
            t
        };

        let http = {
            let mut h = HttpConfig {
                cors_origins: vec!["http://localhost".into()],
            };
            if let Some(mut r) = Reader::new(&mut errors, "http", get("http"), "HttpConfig") {
                h.cors_origins = r.string_list("cors_origins", vec!["http://localhost".into()]);
            }
            h
        };

        let git = {
            let mut g = GitConfig {
                provider: GitProviderName::Github,
                pat_user_env: "GIT_USER".into(),
                pat_token_env: "GIT_TOKEN".into(),
                author_name: "Kumoss".into(),
                author_email: "kumoss@noreply.invalid".into(),
            };
            if let Some(mut r) = Reader::new(&mut errors, "git", get("git"), "GitConfig") {
                g.provider = coerce_enum(
                    &mut r,
                    "provider",
                    GitProviderName::Github,
                    "GitProviderName",
                    GitProviderName::from_name,
                    GitProviderName::from_value,
                    GitProviderName::expected(),
                );
                g.pat_user_env = r.string("pat_user_env", "GIT_USER");
                g.pat_token_env = r.string("pat_token_env", "GIT_TOKEN");
                g.author_name = r.string("author_name", "Kumoss");
                g.author_email = r.string("author_email", "kumoss@noreply.invalid");
            }
            g
        };

        if !errors.is_empty() {
            return Err(ConfigError(format!(
                "{} validation error{} for SystemConfig\n{}",
                errors.len(),
                if errors.len() == 1 { "" } else { "s" },
                errors.join("\n")
            )));
        }

        let cfg = SystemConfig {
            environment,
            oidc,
            admin,
            llm,
            web_search,
            services,
            orchestration,
            paths,
            database,
            redis,
            storage,
            telemetry,
            http,
            git,
        };
        cfg.assert_service_tokens()?;
        cfg.assert_service_endpoints()?;
        Ok(cfg)
    }

    /// Every service the core will call needs a bearer token resolved.
    fn assert_service_tokens(&self) -> Result<(), ConfigError> {
        let mut missing: Vec<String> = Vec::new();
        if self.services.iac.token().is_empty() {
            missing.push(format!("services.iac → ${}", self.services.iac.token_env));
        }
        if self.services.llm.token().is_empty() {
            missing.push(format!("services.llm → ${}", self.services.llm.token_env));
        }
        for (name, svc) in [
            ("notifications", &self.services.notifications),
            ("mapping", &self.services.mapping),
            ("authz", &self.services.authz),
        ] {
            if svc.enabled && svc.token().is_empty() {
                missing.push(format!("services.{name} → ${}", svc.token_env));
            }
        }
        if !missing.is_empty() {
            return Err(ConfigError(format!(
                "1 validation error for SystemConfig\n  Value error, Services the core calls have no bearer token in the environment: {}. Set the listed env vars; the optional sidecars can also be flipped to enabled: false (services.iac and services.llm cannot — they are mandatory).",
                missing.join("; ")
            )));
        }
        Ok(())
    }

    /// An enabled optional sidecar needs an endpoint to call: a blank one
    /// would read like `enabled: false`, which for authz fails open.
    fn assert_service_endpoints(&self) -> Result<(), ConfigError> {
        let missing: Vec<String> = [
            ("notifications", &self.services.notifications),
            ("mapping", &self.services.mapping),
            ("authz", &self.services.authz),
        ]
        .iter()
        .filter(|(_, svc)| svc.enabled && svc.endpoint.is_empty())
        .map(|(name, _)| format!("services.{name}.endpoint"))
        .collect();
        if !missing.is_empty() {
            return Err(ConfigError(format!(
                "1 validation error for SystemConfig\n  Value error, Enabled services have no endpoint: {}. Point each at an implementation of its contract, or flip it to enabled: false.",
                missing.join("; ")
            )));
        }
        Ok(())
    }

    /// Load from YAML if `KUMOSS_CONFIG` (or the default path) is a real
    /// file; else defaults. A directory there — what docker-compose creates
    /// when the mounted host file is missing — reads as absent.
    pub fn load() -> Result<Self, ConfigError> {
        let path = std::env::var("KUMOSS_CONFIG")
            .ok()
            .filter(|p| !p.is_empty())
            .unwrap_or_else(|| "/etc/kumoss/config.yaml".to_string());
        let p = std::path::Path::new(&path);
        if p.is_file() {
            let text = std::fs::read_to_string(p).map_err(|e| ConfigError(format!("cannot read {path}: {e}")))?;
            let data = crate::shared::yaml::safe_load(&text).map_err(|e| ConfigError(e.0))?;
            let data = if data.is_null() {
                Value::Object(Map::new())
            } else {
                data
            };
            return Self::from_value(&data);
        }
        Self::from_value(&Value::Object(Map::new()))
    }

    /// `f"{collector_url}v1/traces"`.
    pub fn otlp_traces_endpoint(&self) -> String {
        format!("{}v1/traces", self.telemetry.collector_url)
    }
}

static CONFIG: LazyLock<std::sync::RwLock<Option<&'static SystemConfig>>> =
    LazyLock::new(|| std::sync::RwLock::new(None));

/// Install the process-wide configuration (once, at boot or in tests).
pub fn install(cfg: SystemConfig) -> &'static SystemConfig {
    let leaked: &'static SystemConfig = Box::leak(Box::new(cfg));
    *CONFIG.write().expect("config lock") = Some(leaked);
    leaked
}

/// The process-wide configuration.
pub fn system_config() -> &'static SystemConfig {
    CONFIG
        .read()
        .expect("config lock")
        .expect("system config not installed")
}

/// Parse a URL with the `url` crate, for clients that need a real one.
pub fn parse_url(raw: &str) -> Option<Url> {
    Url::parse(raw).ok()
}

#[cfg(test)]
pub(crate) mod test_support {
    use super::*;

    /// A configuration with every mandatory secret set, for unit tests.
    pub fn test_config(overrides: Value) -> SystemConfig {
        // SAFETY: tests run single-threaded with respect to these vars' values
        // (they only ever set the same constants).
        unsafe {
            std::env::set_var("KUMOSS_TEST_DB_URL", "postgresql://u:p@localhost:5432/db");
            std::env::set_var("KUMOSS_TEST_IAC_TOKEN", "iac-token");
            std::env::set_var("KUMOSS_TEST_LLM_TOKEN", "llm-token");
        }
        let mut base = serde_json::json!({
            "database": {"kumoss_database_url_env": "KUMOSS_TEST_DB_URL"},
            "services": {
                "iac": {"token_env": "KUMOSS_TEST_IAC_TOKEN"},
                "llm": {"token_env": "KUMOSS_TEST_LLM_TOKEN"}
            }
        });
        merge(&mut base, &overrides);
        SystemConfig::from_value(&base).expect("valid test config")
    }

    fn merge(base: &mut Value, over: &Value) {
        match (base, over) {
            (Value::Object(b), Value::Object(o)) => {
                for (k, v) in o {
                    merge(b.entry(k.clone()).or_insert(Value::Null), v);
                }
            }
            (b, o) => *b = o.clone(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::test_support::test_config;
    use super::*;
    use serde_json::json;

    #[test]
    fn defaults_load() {
        let cfg = test_config(json!({}));
        assert_eq!(cfg.environment, "development");
        assert_eq!(cfg.oidc.scope, "openid profile email");
        assert_eq!(cfg.storage.provider, ObjectStorageProvider::Rustfs);
        assert_eq!(cfg.git.provider, GitProviderName::Github);
        assert_eq!(cfg.orchestration.max_validation_iteration, 8);
    }

    #[test]
    fn entra_scope_is_expanded() {
        let cfg = test_config(
            json!({"oidc": {"issuer_url": "https://login.microsoftonline.com/t/v2.0", "client_id": "abc"}}),
        );
        assert_eq!(cfg.oidc.scope, "openid profile email api://abc/.default");
    }

    #[test]
    fn issuer_without_client_id_fails() {
        let mut base = json!({});
        base["oidc"] = json!({"issuer_url": "https://idp"});
        let err = SystemConfig::from_value(&json!({"oidc": {"issuer_url": "https://idp"}}));
        assert!(err.is_err());
        let _ = base;
    }

    #[test]
    fn yaml_null_section_is_rejected() {
        unsafe {
            std::env::set_var("KUMOSS_TEST_DB_URL", "postgresql://u:p@localhost:5432/db");
            std::env::set_var("KUMOSS_TEST_IAC_TOKEN", "iac-token");
            std::env::set_var("KUMOSS_TEST_LLM_TOKEN", "llm-token");
        }
        let v = json!({
            "database": {"kumoss_database_url_env": "KUMOSS_TEST_DB_URL"},
            "services": {"iac": {"token_env": "KUMOSS_TEST_IAC_TOKEN"}, "llm": {"token_env": "KUMOSS_TEST_LLM_TOKEN"}},
            "storage": {"terraform_state_bucket": null}
        });
        let err = SystemConfig::from_value(&v).unwrap_err();
        assert!(err.0.contains("storage.terraform_state_bucket"), "{}", err.0);
    }

    #[test]
    fn provider_accepts_name_or_value() {
        let cfg = test_config(json!({"git": {"provider": "dev.azure.com"}}));
        assert_eq!(cfg.git.provider, GitProviderName::AzureDevops);
        let cfg = test_config(json!({"git": {"provider": "GITLAB"}}));
        assert_eq!(cfg.git.provider, GitProviderName::Gitlab);
    }

    #[test]
    fn presign_bounds() {
        unsafe {
            std::env::set_var("KUMOSS_TEST_DB_URL", "postgresql://u:p@localhost:5432/db");
            std::env::set_var("KUMOSS_TEST_IAC_TOKEN", "iac-token");
            std::env::set_var("KUMOSS_TEST_LLM_TOKEN", "llm-token");
        }
        let v = json!({
            "database": {"kumoss_database_url_env": "KUMOSS_TEST_DB_URL"},
            "services": {"iac": {"token_env": "KUMOSS_TEST_IAC_TOKEN"}, "llm": {"token_env": "KUMOSS_TEST_LLM_TOKEN"}},
            "storage": {"presign_expiry_seconds": 3600}
        });
        assert!(SystemConfig::from_value(&v).is_err());
    }

    #[test]
    fn storage_account_name_forms() {
        let mut cfg = test_config(json!({}));
        cfg.storage.endpoint_url = "https://acct.blob.core.windows.net".into();
        assert_eq!(cfg.storage.storage_account_name().unwrap(), "acct");
        cfg.storage.endpoint_url = "http://127.0.0.1:10000/devstoreaccount1".into();
        assert_eq!(cfg.storage.storage_account_name().unwrap(), "devstoreaccount1");
        cfg.storage.endpoint_url = "http://object-storage:9000".into();
        assert!(cfg.storage.storage_account_name().is_err());
    }

    #[test]
    fn urlsplit_matches_python() {
        let p = urlsplit("https://org@dev.azure.com/org/p/_git/r");
        assert_eq!(p.scheme, "https");
        assert_eq!(p.username.as_deref(), Some("org"));
        assert_eq!(p.password, None);
        assert_eq!(p.hostname.as_deref(), Some("dev.azure.com"));
        let p = urlsplit("https://user:@GitHub.com/a/b.git");
        assert_eq!(p.password.as_deref(), Some(""));
        assert_eq!(p.hostname.as_deref(), Some("github.com"));
        assert_eq!(p.path, "/a/b.git");
    }
}
