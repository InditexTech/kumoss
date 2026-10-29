// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

//! Azure storage-account adapter on the Blob REST API (SharedKey auth).

use std::cmp::Ordering;
use std::sync::LazyLock;
use std::time::Duration;

use async_trait::async_trait;
use base64::Engine as _;
use base64::engine::{DecodePaddingMode, GeneralPurpose, GeneralPurposeConfig};
use chrono::{DateTime, Utc};
use hmac::{Hmac, Mac};
use percent_encoding::{AsciiSet, NON_ALPHANUMERIC, utf8_percent_encode};
use rand::Rng as _;
use regex::Regex;
use reqwest::Method;
use reqwest::header::{HeaderMap, HeaderName, HeaderValue};
use sha2::Sha256;

use crate::domain::ports::{ObjectMetadata, ObjectStorage};
use crate::shared::config::urlsplit;
use crate::shared::error::{AppError, AppResult, ErrorKind};

/// The service version `azure-storage-blob` 12.31.0 sends and signs
/// (`X_MS_VERSION`). Azurite needs `--skipApiVersionCheck` for it, exactly as
/// it does for the Python SDK.
pub const X_MS_VERSION: &str = "2026-10-06";

const METADATA_HEADER_PREFIX: &str = "x-ms-meta-";

/// Python's `urllib.parse.quote(s)` (default `safe='/'`; letters, digits and
/// `_.-~` are never quoted).
const QUOTE_SET: &AsciiSet = &NON_ALPHANUMERIC
    .remove(b'_')
    .remove(b'.')
    .remove(b'-')
    .remove(b'~')
    .remove(b'/');

/// `urllib.parse.quote(value)`.
pub fn py_quote(value: &str) -> String {
    utf8_percent_encode(value, QUOTE_SET).to_string()
}

/// Construction parameters of [`StorageAccountObjectStorage`].
#[derive(Debug, Clone)]
pub struct AzureOptions {
    /// Container holding every object this adapter touches.
    pub container: String,
    /// Account name (derived from `endpoint_url` by the config layer; passed
    /// explicitly because SAS signing and path-style endpoints cannot
    /// re-derive it reliably).
    pub account: String,
    /// Account blob endpoint for API calls,
    /// `https://<account>.blob.core.windows.net` or an emulator-style
    /// `http://<host>:<port>/<account>`.
    pub endpoint_url: String,
    /// Base for browser-facing SAS URLs; None or empty reuses `endpoint_url`.
    pub public_endpoint_url: Option<String>,
    /// Shared key (base64) for request signing and local SAS signing.
    pub account_key: String,
    /// Default validity of SAS GET URLs.
    pub presign_expiry_seconds: u64,
    /// Seconds to establish a connection.
    pub connect_timeout: f64,
    /// Seconds to wait on a response.
    pub read_timeout: f64,
    /// The SDK's `retry_total`: retries on top of the first attempt.
    pub max_attempts: u32,
}

impl AzureOptions {
    /// The Python constructor's defaults: 3s/10s timeouts, retry_total 3.
    pub fn new(
        container: impl Into<String>,
        account: impl Into<String>,
        endpoint_url: impl Into<String>,
        account_key: impl Into<String>,
        presign_expiry_seconds: u64,
    ) -> Self {
        Self {
            container: container.into(),
            account: account.into(),
            endpoint_url: endpoint_url.into(),
            public_endpoint_url: None,
            account_key: account_key.into(),
            presign_expiry_seconds,
            connect_timeout: 3.0,
            read_timeout: 10.0,
            max_attempts: 3,
        }
    }
}

/// `azure.storage.blob.ExponentialRetry` backoff: the n-th retry (n >= 1)
/// sleeps `uniform(b - jitter, b + jitter)` seconds, `b = initial + base^n`.
#[derive(Debug, Clone, Copy)]
pub(crate) struct Backoff {
    pub initial: f64,
    pub base: f64,
    pub jitter: f64,
}

impl Backoff {
    const SDK: Backoff = Backoff {
        initial: 15.0,
        base: 3.0,
        jitter: 3.0,
    };

    fn delay(&self, count: u32) -> Duration {
        let backoff = self.initial + if count == 0 { 0.0 } else { self.base.powi(count as i32) };
        let start = if backoff > self.jitter {
            backoff - self.jitter
        } else {
            0.0
        };
        let end = backoff + self.jitter;
        let secs = if end > start {
            rand::rng().random_range(start..end)
        } else {
            start
        };
        Duration::try_from_secs_f64(secs.max(0.0)).unwrap_or(Duration::ZERO)
    }
}

/// Azure storage-account adapter, a port of the Python one built on the sync
/// blob SDK, speaking the Blob REST API directly.
///
/// The account name is not configured separately: the config layer derives it
/// from `endpoint_url` (see `StorageConfig`). An account-key SAS signs the
/// canonical resource path, not the host, so browser URLs are string-built on
/// `public_endpoint_url` while API calls hit `endpoint_url`. For a real public
/// storage account both are the same host; they differ only in emulator-style
/// split setups.
#[derive(Debug, Clone)]
pub struct StorageAccountObjectStorage {
    container: String,
    account: String,
    account_key: String,
    presign_expiry: u64,
    public_base: String,
    /// `scheme://primary_hostname`, the SDK's request base: the netloc for
    /// `*.blob.core.*` hosts, netloc + path (the account) for emulators.
    service_base: String,
    retry_total: u32,
    pub(crate) backoff: Backoff,
    http: reqwest::Client,
}

fn seconds(value: f64) -> Duration {
    Duration::try_from_secs_f64(value.max(0.0)).unwrap_or(Duration::MAX)
}

impl StorageAccountObjectStorage {
    /// Build the client (no IO). Fails like `BlobServiceClient` does on an
    /// endpoint without a host.
    pub fn new(opts: AzureOptions) -> AppResult<Self> {
        let service_base = service_base(&opts.endpoint_url)?;
        let public = opts
            .public_endpoint_url
            .as_deref()
            .filter(|p| !p.is_empty())
            .unwrap_or(&opts.endpoint_url);
        let http = reqwest::Client::builder()
            .connect_timeout(seconds(opts.connect_timeout))
            .read_timeout(seconds(opts.read_timeout))
            // A redirect would need re-signing; the blob service never sends one.
            .redirect(reqwest::redirect::Policy::none())
            .build()
            .map_err(|e| AppError::internal(e.to_string()))?;
        Ok(Self {
            container: opts.container,
            account: opts.account,
            account_key: opts.account_key,
            presign_expiry: opts.presign_expiry_seconds,
            public_base: public.trim_end_matches('/').to_string(),
            service_base,
            retry_total: opts.max_attempts,
            backoff: Backoff::SDK,
            http,
        })
    }

    pub fn container(&self) -> &str {
        &self.container
    }

    fn target(&self, key: &str) -> String {
        if key.is_empty() {
            self.container.clone()
        } else {
            format!("{}/{}", self.container, key)
        }
    }

    fn container_url(&self) -> String {
        format!("{}/{}", self.service_base, py_quote(&self.container))
    }

    fn blob_url(&self, key: &str) -> String {
        // `quote(blob_name, safe='~/')`: '~' is never quoted anyway.
        format!("{}/{}/{}", self.service_base, py_quote(&self.container), py_quote(key))
    }

    /// Map any failure onto the domain errors (port contract), logging the
    /// same line the Python adapter did.
    fn translate(&self, failure: Failure, op: &str, key: &str) -> AppError {
        let target = self.target(key);
        let text = failure.text();
        tracing::error!("Object storage {op} failed on '{target}': {text}");
        match failure {
            // Request never sent / response never received: connectivity.
            Failure::Request(_) | Failure::Response(_) => AppError::kind(
                ErrorKind::ObjectStorageUnavailable,
                format!("Object store unreachable during {op} on '{target}'."),
                503,
            ),
            Failure::Status(ref e) if e.class == ErrorClass::NotFound => {
                AppError::kind(ErrorKind::ObjectNotFound, format!("Object '{target}' not found."), 404)
            }
            _ => AppError::kind(
                ErrorKind::ObjectStorage,
                format!("Object storage {op} failed on '{target}': {text}"),
                500,
            ),
        }
    }

    /// One logical operation: signed, sent, and retried like the SDK's
    /// `ExponentialRetry(retry_total=max_attempts)` pipeline.
    async fn send(&self, request: &Request<'_>) -> Result<Reply, Failure> {
        let mut counters = RetryCounters::new(self.retry_total);
        loop {
            let outcome = self.attempt(request).await;
            let kind = match &outcome {
                Ok(reply) if is_retry(reply) => RetryKind::Status,
                Ok(_) => return outcome,
                Err(Failure::Request(_)) => RetryKind::Connect,
                Err(Failure::Response(_)) => RetryKind::Read,
                Err(_) => return outcome,
            };
            if !counters.increment(kind) {
                return outcome;
            }
            tokio::time::sleep(self.backoff.delay(counters.count)).await;
        }
    }

    async fn attempt(&self, request: &Request<'_>) -> Result<Reply, Failure> {
        let key = decode_account_key(&self.account_key).map_err(Failure::Other)?;
        let date = Utc::now().format("%a, %d %b %Y %H:%M:%S GMT").to_string();
        let mut x_ms: Vec<(String, String)> = request.headers.clone();
        x_ms.push(("x-ms-version".into(), X_MS_VERSION.into()));
        x_ms.push(("x-ms-date".into(), date));
        x_ms.push(("x-ms-client-request-id".into(), uuid::Uuid::new_v4().to_string()));

        let path = urlsplit(&request.url).path;
        let content_length = request.body.as_ref().map(|b| b.len()).unwrap_or(0);
        let string_to_sign = shared_key_string_to_sign(
            request.method.as_str(),
            &StandardHeaders {
                content_length,
                content_type: request.content_type,
            },
            &x_ms,
            &self.account,
            &path,
            &request.query,
        );
        let signature = sign(&key, &string_to_sign);

        let mut headers = HeaderMap::new();
        for (name, value) in &x_ms {
            let name = HeaderName::from_bytes(name.as_bytes())
                .map_err(|e| Failure::Other(format!("Invalid header name {name:?}: {e}")))?;
            let value = HeaderValue::from_str(value)
                .map_err(|e| Failure::Other(format!("Invalid header value {value:?}: {e}")))?;
            headers.insert(name, value);
        }
        if let Some(content_type) = request.content_type {
            headers.insert(reqwest::header::CONTENT_TYPE, HeaderValue::from_static(content_type));
        }
        headers.insert(reqwest::header::ACCEPT, HeaderValue::from_static("application/xml"));
        let auth = format!("SharedKey {}:{}", self.account, signature);
        headers.insert(
            reqwest::header::AUTHORIZATION,
            HeaderValue::from_str(&auth).map_err(|e| Failure::Other(e.to_string()))?,
        );

        let mut url = request.url.clone();
        if !request.query.is_empty() {
            let query: Vec<String> = request.query.iter().map(|(k, v)| format!("{k}={v}")).collect();
            url = format!("{url}?{}", query.join("&"));
        }
        let mut builder = self.http.request(request.method.clone(), &url).headers(headers);
        if let Some(body) = &request.body {
            // Put Blob requires the length even for an empty body.
            builder = builder
                .header(reqwest::header::CONTENT_LENGTH, body.len())
                .body(body.clone());
        }
        let response = builder.send().await.map_err(|e| classify_reqwest(&e))?;
        let status = response.status().as_u16();
        let headers = response.headers().clone();
        // Reading the body is part of receiving the response.
        let body = response.bytes().await.map_err(|e| Failure::Response(error_chain(&e)))?;
        Ok(Reply {
            status,
            headers,
            body: body.to_vec(),
        })
    }

    /// The reply when its status is one the operation expects; otherwise the
    /// translated `HttpResponseError`.
    fn expect(reply: Reply, ok: &[u16]) -> Result<Reply, Failure> {
        if ok.contains(&reply.status) {
            Ok(reply)
        } else {
            Err(Failure::Status(StorageError::from_reply(&reply)))
        }
    }

    fn check_key(key: &str) -> Result<(), Failure> {
        if key.is_empty() {
            return Err(Failure::Other("Please specify a container name and blob name.".into()));
        }
        Ok(())
    }

    async fn ensure_bucket_inner(&self) -> Result<(), Failure> {
        let request = Request::new(Method::PUT, self.container_url()).query("restype", "container");
        match self.send(&request).await.and_then(|r| Self::expect(r, &[201])) {
            Ok(_) => Ok(()),
            // Already there, or two replicas racing the same boot.
            Err(Failure::Status(e)) if e.class == ErrorClass::Exists => Ok(()),
            Err(e) => Err(e),
        }
    }

    async fn put_inner(
        &self,
        key: &str,
        data: Vec<u8>,
        content_type: &str,
        metadata: &ObjectMetadata,
    ) -> Result<(), Failure> {
        Self::check_key(key)?;
        // overwrite: parity with S3 put semantics (last write wins).
        let mut request = Request::new(Method::PUT, self.blob_url(key));
        for (name, value) in metadata {
            request
                .headers
                .push((format!("{METADATA_HEADER_PREFIX}{name}"), value.clone()));
        }
        request.headers.push(("x-ms-blob-type".into(), "BlockBlob".into()));
        request
            .headers
            .push(("x-ms-blob-content-type".into(), content_type.to_string()));
        request.content_type = Some("application/octet-stream");
        request.body = Some(data);
        self.send(&request)
            .await
            .and_then(|r| Self::expect(r, &[201]))
            .map(|_| ())
    }

    async fn get_inner(&self, key: &str) -> Result<Vec<u8>, Failure> {
        Self::check_key(key)?;
        let request = Request::new(Method::GET, self.blob_url(key));
        self.send(&request)
            .await
            .and_then(|r| Self::expect(r, &[200, 206]))
            .map(|r| r.body)
    }

    async fn exists_inner(&self, key: &str) -> Result<bool, Failure> {
        Self::check_key(key)?;
        let request = Request::new(Method::HEAD, self.blob_url(key));
        let reply = self.send(&request).await?;
        match reply.status {
            200 => Ok(true),
            // Encrypted with a customer-provided key: it exists.
            409 => Ok(true),
            _ => {
                let error = StorageError::from_reply(&reply);
                if error.class == ErrorClass::NotFound {
                    Ok(false)
                } else {
                    Err(Failure::Status(error))
                }
            }
        }
    }

    async fn delete_inner(&self, key: &str) -> Result<(), Failure> {
        Self::check_key(key)?;
        let request = Request::new(Method::DELETE, self.blob_url(key));
        match self.send(&request).await.and_then(|r| Self::expect(r, &[202])) {
            Ok(_) => Ok(()),
            // Azure 404s absent keys; the port wants idempotent deletes.
            Err(Failure::Status(e)) if e.class == ErrorClass::NotFound => Ok(()),
            Err(e) => Err(e),
        }
    }

    fn presign_inner(&self, key: &str, expires_in: Option<u64>) -> Result<String, Failure> {
        let seconds = expires_in.filter(|s| *s != 0).unwrap_or(self.presign_expiry);
        let expiry = Utc::now() + chrono::Duration::seconds(i64::try_from(seconds).unwrap_or(i64::MAX));
        let sas = generate_blob_sas(&self.account, &self.container, key, &self.account_key, expiry)
            .map_err(Failure::Other)?;
        // SAS binds the resource path, not the host: safe to build on
        // whichever base the browser reaches.
        Ok(format!(
            "{}/{}/{}?{}",
            self.public_base,
            self.container,
            py_quote(key),
            sas
        ))
    }
}

#[async_trait]
impl ObjectStorage for StorageAccountObjectStorage {
    async fn ensure_bucket(&self) -> AppResult<()> {
        self.ensure_bucket_inner()
            .await
            .map_err(|f| self.translate(f, "ensure_bucket", ""))
    }

    async fn put(&self, key: &str, data: Vec<u8>, content_type: &str, metadata: &ObjectMetadata) -> AppResult<()> {
        self.put_inner(key, data, content_type, metadata)
            .await
            .map_err(|f| self.translate(f, "put", key))
    }

    fn metadata_header_prefix(&self) -> &'static str {
        METADATA_HEADER_PREFIX
    }

    async fn get(&self, key: &str) -> AppResult<Vec<u8>> {
        self.get_inner(key).await.map_err(|f| self.translate(f, "get", key))
    }

    async fn exists(&self, key: &str) -> AppResult<bool> {
        self.exists_inner(key)
            .await
            .map_err(|f| self.translate(f, "exists", key))
    }

    async fn delete(&self, key: &str) -> AppResult<()> {
        self.delete_inner(key)
            .await
            .map_err(|f| self.translate(f, "delete", key))
    }

    async fn presigned_get_url(&self, key: &str, expires_in: Option<u64>) -> AppResult<String> {
        self.presign_inner(key, expires_in)
            .map_err(|f| self.translate(f, "presign", key))
    }
}

// --- endpoint ---------------------------------------------------------------

/// `scheme://primary_hostname` as `StorageAccountHostsMixin` derives it.
fn service_base(endpoint_url: &str) -> AppResult<String> {
    let account_url = if endpoint_url.to_lowercase().starts_with("http") {
        endpoint_url.to_string()
    } else {
        format!("https://{endpoint_url}")
    };
    let parsed = urlsplit(account_url.trim_end_matches('/'));
    if parsed.netloc.is_empty() {
        return Err(AppError::internal(format!("Invalid URL: {account_url}")));
    }
    let primary = if parsed.netloc.split(".blob.core.").count() > 1 {
        parsed.netloc.clone()
    } else {
        format!("{}{}", parsed.netloc, parsed.path)
            .trim_end_matches('/')
            .to_string()
    };
    Ok(format!("{}://{}", parsed.scheme, primary))
}

// --- signing ----------------------------------------------------------------

/// Python's lenient `base64.b64decode`: characters outside the alphabet are
/// discarded, padding is required.
fn decode_account_key(key: &str) -> Result<Vec<u8>, String> {
    let cleaned: String = key
        .chars()
        .filter(|c| c.is_ascii_alphanumeric() || matches!(c, '+' | '/' | '='))
        .collect();
    let data_chars = cleaned.trim_end_matches('=').len();
    let engine = GeneralPurpose::new(
        &base64::alphabet::STANDARD,
        GeneralPurposeConfig::new()
            .with_decode_allow_trailing_bits(true)
            .with_decode_padding_mode(DecodePaddingMode::RequireCanonical),
    );
    engine.decode(cleaned.as_bytes()).map_err(|_| {
        if data_chars % 4 == 1 {
            format!(
                "Invalid base64-encoded string: number of data characters ({data_chars}) cannot be 1 more than a multiple of 4"
            )
        } else {
            "Incorrect padding".to_string()
        }
    })
}

/// `sign_string`: base64(HMAC-SHA256(key, utf8(string_to_sign))).
fn sign(key: &[u8], string_to_sign: &str) -> String {
    let mut mac = Hmac::<Sha256>::new_from_slice(key).expect("HMAC takes keys of any length");
    mac.update(string_to_sign.as_bytes());
    base64::engine::general_purpose::STANDARD.encode(mac.finalize().into_bytes())
}

/// The standard headers this adapter ever sends among the SharedKey ones.
struct StandardHeaders<'a> {
    content_length: usize,
    content_type: Option<&'a str>,
}

/// `SharedKeyCredentialPolicy.on_request`'s string to sign. `x_ms` names
/// must be lowercase; `path` is the request URL's (encoded) path.
fn shared_key_string_to_sign(
    method: &str,
    standard: &StandardHeaders<'_>,
    x_ms: &[(String, String)],
    account: &str,
    path: &str,
    query: &[(&str, &str)],
) -> String {
    // content-encoding, content-language, content-length (omitted when 0),
    // content-md5, content-type, date, if-modified-since, if-match,
    // if-none-match, if-unmodified-since, range.
    let length = if standard.content_length == 0 {
        String::new()
    } else {
        standard.content_length.to_string()
    };
    let values = [
        "",
        "",
        length.as_str(),
        "",
        standard.content_type.unwrap_or(""),
        "",
        "",
        "",
        "",
        "",
        "",
    ];
    let mut out = format!("{method}\n{}\n", values.join("\n"));

    let mut headers: Vec<(String, &str)> = x_ms
        .iter()
        .filter(|(name, _)| name.starts_with("x-ms-"))
        .map(|(name, value)| (name.to_lowercase(), value.as_str()))
        .collect();
    headers.sort_by(|a, b| compare_headers(&a.0, &b.0));
    for (name, value) in headers {
        out.push_str(&format!("{name}:{value}\n"));
    }

    out.push('/');
    out.push_str(account);
    out.push_str(path);

    let mut sorted: Vec<(&str, &str)> = query.to_vec();
    sorted.sort();
    for (name, value) in sorted {
        let value = percent_encoding::percent_decode_str(value).decode_utf8_lossy();
        out.push_str(&format!("\n{}:{}", name.to_lowercase(), value));
    }
    out
}

#[rustfmt::skip]
const TABLE_LV0: [u16; 128] = [
    0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0,
    0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0,
    0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x71c, 0x0, 0x71f, 0x721, 0x723, 0x725,
    0x0, 0x0, 0x0, 0x72d, 0x803, 0x0, 0x0, 0x733, 0x0, 0xd03, 0xd1a, 0xd1c, 0xd1e,
    0xd20, 0xd22, 0xd24, 0xd26, 0xd28, 0xd2a, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0,
    0xe02, 0xe09, 0xe0a, 0xe1a, 0xe21, 0xe23, 0xe25, 0xe2c, 0xe32, 0xe35, 0xe36, 0xe48, 0xe51,
    0xe70, 0xe7c, 0xe7e, 0xe89, 0xe8a, 0xe91, 0xe99, 0xe9f, 0xea2, 0xea4, 0xea6, 0xea7, 0xea9,
    0x0, 0x0, 0x0, 0x743, 0x744, 0x748, 0xe02, 0xe09, 0xe0a, 0xe1a, 0xe21, 0xe23, 0xe25,
    0xe2c, 0xe32, 0xe35, 0xe36, 0xe48, 0xe51, 0xe70, 0xe7c, 0xe7e, 0xe89, 0xe8a, 0xe91, 0xe99,
    0xe9f, 0xea2, 0xea4, 0xea6, 0xea7, 0xea9, 0x0, 0x74c, 0x0, 0x750, 0x0,
];

#[rustfmt::skip]
const TABLE_LV4: [u16; 128] = [
    0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0,
    0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0,
    0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x8012, 0x0, 0x0, 0x0, 0x0, 0x0, 0x8212, 0x0, 0x0,
    0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0,
    0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0,
    0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0,
    0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0,
    0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0,
];

/// The SDK's `_storage_header_sort` collation (the service's own ordering of
/// canonicalized headers; `-` and `_` weigh in only on a tie).
fn compare_headers(lhs: &str, rhs: &str) -> Ordering {
    let tables: [&[u16; 128]; 2] = [&TABLE_LV0, &TABLE_LV4];
    let (lhs, rhs) = (lhs.as_bytes(), rhs.as_bytes());
    let weight = |table: &[u16; 128], s: &[u8], i: usize| -> u16 {
        if i < s.len() {
            table.get(s[i] as usize).copied().unwrap_or(0)
        } else {
            0x1
        }
    };
    let (mut level, mut i, mut j) = (0usize, 0usize, 0usize);
    while level < tables.len() {
        if level == tables.len() - 1 && i != j {
            return if i > j { Ordering::Less } else { Ordering::Greater };
        }
        let w1 = weight(tables[level], lhs, i);
        let w2 = weight(tables[level], rhs, j);
        if w1 == 0x1 && w2 == 0x1 {
            i = 0;
            j = 0;
            level += 1;
        } else if w1 == w2 {
            i += 1;
            j += 1;
        } else if w1 == 0 {
            i += 1;
        } else if w2 == 0 {
            j += 1;
        } else {
            return w1.cmp(&w2);
        }
    }
    Ordering::Equal
}

/// `generate_blob_sas(account_name, container_name, blob_name, account_key,
/// permission=BlobSasPermissions(read=True), expiry=expiry)`: a Service SAS
/// query string, byte-identical to the SDK's (same signed fields, version,
/// order and quoting).
pub fn generate_blob_sas(
    account: &str,
    container: &str,
    blob: &str,
    account_key: &str,
    expiry: DateTime<Utc>,
) -> Result<String, String> {
    let se = expiry.format("%Y-%m-%dT%H:%M:%SZ").to_string();
    let mut resource = format!("{container}/{blob}");
    if !resource.starts_with('/') {
        resource.insert(0, '/');
    }
    // sp, st, se, canonicalized resource, si, sip, spr, sv, sr, snapshot
    // time, ses, rscc, rscd, rsce, rscl, rsct; trailing newline dropped.
    let string_to_sign = format!("r\n\n{se}\n/blob/{account}{resource}\n\n\n\n{X_MS_VERSION}\nb\n\n\n\n\n\n\n");
    let key = decode_account_key(account_key)?;
    let signature = sign(&key, &string_to_sign);
    Ok(format!(
        "se={}&sp=r&sv={}&sr=b&sig={}",
        py_quote(&se),
        py_quote(X_MS_VERSION),
        py_quote(&signature)
    ))
}

// --- transport --------------------------------------------------------------

#[derive(Debug, Clone)]
struct Request<'a> {
    method: Method,
    url: String,
    query: Vec<(&'a str, &'a str)>,
    /// Extra `x-ms-*` headers, lowercase names.
    headers: Vec<(String, String)>,
    content_type: Option<&'static str>,
    body: Option<Vec<u8>>,
}

impl<'a> Request<'a> {
    fn new(method: Method, url: String) -> Self {
        Self {
            method,
            url,
            query: Vec::new(),
            headers: Vec::new(),
            content_type: None,
            body: None,
        }
    }

    fn query(mut self, name: &'a str, value: &'a str) -> Self {
        self.query.push((name, value));
        self
    }
}

#[derive(Debug)]
struct Reply {
    status: u16,
    headers: HeaderMap,
    body: Vec<u8>,
}

/// A failure, classified the way azure-core's exception types are.
#[derive(Debug)]
enum Failure {
    /// `ServiceRequestError`: the request never reached the service.
    Request(String),
    /// `ServiceResponseError`: no (complete) response came back.
    Response(String),
    /// `HttpResponseError` and subclasses: the service answered an error.
    Status(StorageError),
    /// Anything else (bad key, invalid header, missing blob name).
    Other(String),
}

impl Failure {
    fn text(&self) -> &str {
        match self {
            Failure::Request(t) | Failure::Response(t) | Failure::Other(t) => t,
            Failure::Status(e) => &e.text,
        }
    }
}

fn error_chain(error: &(dyn std::error::Error + 'static)) -> String {
    let mut text = error.to_string();
    let mut source = error.source();
    while let Some(e) = source {
        let part = e.to_string();
        if !text.contains(&part) {
            text.push_str(": ");
            text.push_str(&part);
        }
        source = e.source();
    }
    text
}

/// requests' transport: connect failures and connect timeouts are
/// `ServiceRequestError`; read timeouts and dropped connections are
/// `ServiceResponseError`.
fn classify_reqwest(error: &reqwest::Error) -> Failure {
    let text = error_chain(error);
    if error.is_builder() {
        Failure::Other(text)
    } else if error.is_connect() {
        Failure::Request(text)
    } else {
        Failure::Response(text)
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum RetryKind {
    Connect,
    Read,
    Status,
}

/// `StorageRetryPolicy`'s counters: `retry_total` plus 3 connect, 3 read and
/// 3 status retries; exhausted once any non-zero counter drops below zero.
#[derive(Debug)]
struct RetryCounters {
    total: i64,
    connect: i64,
    read: i64,
    status: i64,
    count: u32,
}

impl RetryCounters {
    fn new(retry_total: u32) -> Self {
        Self {
            total: i64::from(retry_total),
            connect: 3,
            read: 3,
            status: 3,
            count: 0,
        }
    }

    fn exhausted(&self) -> bool {
        [self.total, self.connect, self.read, self.status]
            .iter()
            .filter(|c| **c != 0)
            .any(|c| *c < 0)
    }

    /// Record a failed attempt; true when another attempt is allowed.
    fn increment(&mut self, kind: RetryKind) -> bool {
        self.total -= 1;
        match kind {
            RetryKind::Connect => self.connect -= 1,
            RetryKind::Read => self.read -= 1,
            RetryKind::Status => self.status -= 1,
        }
        if self.exhausted() {
            return false;
        }
        self.count += 1;
        true
    }
}

/// `is_retry` for the primary location: 408, 5xx but 501/505, and a 4xx whose
/// copy-source error code is a transient one.
fn is_retry(reply: &Reply) -> bool {
    let status = reply.status;
    if (300..500).contains(&status) {
        if status == 408 {
            return true;
        }
        if status >= 400 {
            let code = reply
                .headers
                .get("x-ms-copy-source-error-code")
                .and_then(|v| v.to_str().ok());
            return matches!(code, Some("OperationTimedOut" | "InternalError" | "ServerBusy"));
        }
        return false;
    }
    status >= 500 && status != 501 && status != 505
}

// --- error responses ----------------------------------------------------------

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum ErrorClass {
    /// `ResourceNotFoundError`.
    NotFound,
    /// `ResourceExistsError`.
    Exists,
    Other,
}

const NOT_FOUND_CODES: [&str; 7] = [
    "ResourceNotFound",
    "CannotVerifyCopySource",
    "BlobNotFound",
    "QueueNotFound",
    "ContainerNotFound",
    "ParentNotFound",
    "ShareNotFound",
];
const EXISTS_CODES: [&str; 11] = [
    "AccountAlreadyExists",
    "AccountBeingCreated",
    "ResourceAlreadyExists",
    "ResourceTypeMismatch",
    "BlobAlreadyExists",
    "QueueAlreadyExists",
    "ContainerAlreadyExists",
    "ContainerBeingDeleted",
    "QueueBeingDeleted",
    "ShareAlreadyExists",
    "ShareBeingDeleted",
];
const SV_DOCS_URL: &str =
    "https://learn.microsoft.com/rest/api/storageservices/versioning-for-the-azure-storage-services";

/// A service error as `process_storage_error` shapes it: its class and the
/// `str()` of the raised exception.
#[derive(Debug)]
struct StorageError {
    class: ErrorClass,
    text: String,
}

static XML_ERROR: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"(?s)^\s*(?:<\?xml[^>]*\?>)?\s*<([A-Za-z_][\w.\-]*)[^>]*?(?:/>|>(.*)</([A-Za-z_][\w.\-]*)\s*>)\s*$")
        .expect("regex")
});
static XML_CHILD: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"(?s)<([A-Za-z_][\w.\-]*)(?:\s[^>]*?)?(/>|>)").expect("regex"));

fn xml_unescape(text: &str) -> String {
    let mut out = String::with_capacity(text.len());
    let mut rest = text;
    while let Some(i) = rest.find('&') {
        out.push_str(&rest[..i]);
        let tail = &rest[i..];
        let Some(end) = tail.find(';') else {
            out.push_str(tail);
            return out;
        };
        let entity = &tail[1..end];
        let decoded = match entity {
            "lt" => Some('<'),
            "gt" => Some('>'),
            "amp" => Some('&'),
            "quot" => Some('"'),
            "apos" => Some('\''),
            _ if entity.starts_with("#x") => u32::from_str_radix(&entity[2..], 16).ok().and_then(char::from_u32),
            _ if entity.starts_with('#') => entity[1..].parse().ok().and_then(char::from_u32),
            _ => None,
        };
        match decoded {
            Some(c) => out.push(c),
            None => out.push_str(&tail[..=end]),
        }
        rest = &tail[end + 1..];
    }
    out.push_str(rest);
    out
}

/// `{child.tag.lower(): child.text}` over the root element's children, or
/// None when the document does not parse.
fn xml_children(document: &str) -> Option<Vec<(String, Option<String>)>> {
    let root = XML_ERROR.captures(document)?;
    let Some(inner) = root.get(2) else {
        return Some(Vec::new());
    };
    if root.get(3).map(|m| m.as_str()) != Some(&root[1]) {
        return None;
    }
    let inner = inner.as_str();
    let mut children: Vec<(String, Option<String>)> = Vec::new();
    let mut pos = 0;
    while let Some(open) = XML_CHILD.captures_at(inner, pos) {
        let whole = open.get(0).expect("match");
        let tag = open[1].to_string();
        let text = if &open[2] == "/>" {
            pos = whole.end();
            None
        } else {
            let close = format!("</{tag}>");
            let start = whole.end();
            let end = start + inner[start..].find(&close)?;
            pos = end + close.len();
            // ElementTree: `.text` stops at the first nested element; empty is None.
            let raw = &inner[start..end];
            let raw = raw.find('<').map_or(raw, |i| &raw[..i]);
            if raw.is_empty() { None } else { Some(xml_unescape(raw)) }
        };
        let tag = tag.to_lowercase();
        match children.iter_mut().find(|(name, _)| *name == tag) {
            Some(slot) => slot.1 = text,
            None => children.push((tag, text)),
        }
    }
    Some(children)
}

fn json_error_dict(text: &str) -> Option<Vec<(String, Option<String>)>> {
    let value: serde_json::Value = serde_json::from_str(text).ok()?;
    let Some(error) = value.get("error").and_then(|e| e.as_object()) else {
        return Some(Vec::new());
    };
    Some(
        error
            .iter()
            .map(|(k, v)| {
                (
                    k.clone(),
                    if v.is_null() {
                        None
                    } else {
                        Some(v.as_str().map_or_else(|| v.to_string(), str::to_string))
                    },
                )
            })
            .collect(),
    )
}

impl StorageError {
    fn from_reply(reply: &Reply) -> Self {
        let status = reply.status;
        let reason = reqwest::StatusCode::from_u16(status)
            .ok()
            .and_then(|s| s.canonical_reason())
            .unwrap_or("");
        let header = |name: &str| {
            reply
                .headers
                .get(name)
                .and_then(|v| v.to_str().ok())
                .map(str::to_string)
        };
        // `response.text()`: utf-8-sig.
        let body_text = std::str::from_utf8(&reply.body)
            .ok()
            .map(|t| t.strip_prefix('\u{feff}').unwrap_or(t).to_string());

        let mut code = header("x-ms-error-code");
        let mut message = Some(format!("Operation returned an invalid status '{reason}'"));
        let mut additional: Vec<(String, Option<String>)> = Vec::new();

        enum Body {
            Text(String),
            Dict(Vec<(String, Option<String>)>),
            Undecodable,
        }
        let body = match body_text.as_deref() {
            None => Body::Undecodable,
            Some("") => Body::Text(reason.to_string()),
            Some(text) => {
                let mime = header("content-type")
                    .map(|c| c.split(';').next().unwrap_or("").trim().to_lowercase())
                    .unwrap_or_else(|| "application/json".to_string());
                let json_mime =
                    (mime.starts_with("application/") || mime.starts_with("text/")) && mime.ends_with("json");
                if json_mime {
                    json_error_dict(text).map_or(Body::Undecodable, Body::Dict)
                } else if mime.contains("xml") {
                    match xml_children(text) {
                        Some(children) => Body::Dict(children),
                        None => json_error_dict(text).map_or(Body::Undecodable, Body::Dict),
                    }
                } else if mime.starts_with("text/") {
                    Body::Text(text.to_string())
                } else {
                    Body::Undecodable
                }
            }
        };
        let dict = match body {
            Body::Dict(children) => children,
            Body::Text(text) if code.is_none() => vec![("message".to_string(), Some(text))],
            _ => Vec::new(),
        };
        if !dict.is_empty() {
            let get = |name: &str| dict.iter().find(|(k, _)| k == name).and_then(|(_, v)| v.clone());
            code = get("code");
            message = get("message");
            additional = dict
                .iter()
                .filter(|(k, _)| k != "code" && k != "message")
                .cloned()
                .collect();
        }

        let class = if NOT_FOUND_CODES.contains(&code.as_deref().unwrap_or("")) || status == 404 {
            ErrorClass::NotFound
        } else if EXISTS_CODES.contains(&code.as_deref().unwrap_or("")) || status == 409 {
            ErrorClass::Exists
        } else {
            ErrorClass::Other
        };

        let none = |v: &Option<String>| v.clone().unwrap_or_else(|| "None".to_string());
        let mut text = format!("{}\nErrorCode:{}", none(&message), none(&code));
        for (name, info) in &additional {
            text.push_str(&format!("\n{name}:{}", none(info)));
        }
        let header_name = additional
            .iter()
            .find(|(k, _)| k == "headername")
            .and_then(|(_, v)| v.as_deref());
        if header_name == Some("x-ms-version") && code.as_deref() == Some("InvalidHeaderValue") {
            text = format!(
                "The provided service version is not enabled on this storage account.Please see {SV_DOCS_URL} for additional information.\n{text}"
            );
        }
        // HttpResponseError.__str__ appends the raw body, capped at 2048 chars.
        if let Some(body) = body_text.as_deref().filter(|b| !b.is_empty()) {
            text = format!("{text}\nContent: {body}").chars().take(2048).collect();
        }
        Self { class, text }
    }
}

#[cfg(test)]
mod tests {
    //! SAS and SharedKey parity against values captured from
    //! azure-storage-blob 12.31.0, plus behavioral tests against a real
    //! Azurite. Those run when `KUMOSS_TEST_AZURITE_URL` names its blob
    //! account endpoint, e.g.:
    //!
    //! ```text
    //! docker run -d --rm -p 20000:10000 mcr.microsoft.com/azure-storage/azurite \
    //!     azurite-blob --blobHost 0.0.0.0 --blobPort 10000 --loose --skipApiVersionCheck
    //! KUMOSS_TEST_AZURITE_URL=http://127.0.0.1:20000/devstoreaccount1 cargo test --lib storage
    //! ```

    use super::*;
    use chrono::TimeZone;

    /// Azurite's well-known development account key.
    const KEY: &str = "Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw==";
    const ACCOUNT: &str = "devstoreaccount1";
    const EXPIRY: u64 = 172_800;

    fn fixed_expiry() -> DateTime<Utc> {
        // Microseconds are dropped by the SDK's strftime, as here.
        Utc.with_ymd_and_hms(2026, 11, 1, 12, 0, 0).unwrap() + chrono::Duration::microseconds(987_654)
    }

    #[test]
    fn sas_matches_generate_blob_sas() {
        // python: generate_blob_sas(account_name=ACCOUNT, container_name=..., blob_name=...,
        //   account_key=KEY, permission=BlobSasPermissions(read=True),
        //   expiry=datetime(2026, 11, 1, 12, 0, 0, 987654, tzinfo=timezone.utc))
        assert_eq!(
            generate_blob_sas(ACCOUNT, "kumoss-artifacts", "dir/a.txt", KEY, fixed_expiry()).unwrap(),
            "se=2026-11-01T12%3A00%3A00Z&sp=r&sv=2026-10-06&sr=b&sig=M9GsXF9nylqipl2kNuQRjya9NvR7X5LeZu/8pzr2X%2Bk%3D"
        );
        assert_eq!(
            generate_blob_sas(
                ACCOUNT,
                "kumoss-artifacts",
                "sessions/s/rounds/1/code_changes/vars ä+&=?#%~.tf",
                KEY,
                fixed_expiry()
            )
            .unwrap(),
            "se=2026-11-01T12%3A00%3A00Z&sp=r&sv=2026-10-06&sr=b&sig=QwsiymTkBDCczkP9krzZ9X/uZ4T1x76e9kt/NWKlVp4%3D"
        );
    }

    #[test]
    fn presigned_url_is_built_on_the_public_base() {
        let mut opts = AzureOptions::new(
            "kumoss-artifacts",
            ACCOUNT,
            "http://azurite:10000/devstoreaccount1",
            KEY,
            EXPIRY,
        );
        opts.public_endpoint_url = Some("http://127.0.0.1:20000/devstoreaccount1/".into());
        let storage = StorageAccountObjectStorage::new(opts).unwrap();
        let key = "sessions/s/rounds/1/code_changes/vars ä+&=?#%~.tf";
        let url = storage.presign_inner(key, None).unwrap();
        // python: f"{public_base}/{container}/{quote(key)}?{sas}"
        let prefix = "http://127.0.0.1:20000/devstoreaccount1/kumoss-artifacts/sessions/s/rounds/1/code_changes/vars%20%C3%A4%2B%26%3D%3F%23%25~.tf?se=";
        assert!(url.starts_with(prefix), "{url}");
        assert!(url.contains("&sp=r&sv=2026-10-06&sr=b&sig="), "{url}");
        let se = &url[prefix.len()..prefix.len() + "2026-11-01T12%3A00%3A00Z".len()];
        let se = percent_encoding::percent_decode_str(se).decode_utf8().unwrap();
        let se = chrono::NaiveDateTime::parse_from_str(&se, "%Y-%m-%dT%H:%M:%SZ")
            .unwrap()
            .and_utc();
        let drift = (se - Utc::now()).num_seconds() - EXPIRY as i64;
        assert!((-5..=1).contains(&drift), "expiry off by {drift}s");
        // `expires_in or default`.
        let url = storage.presign_inner(key, Some(0)).unwrap();
        assert!(url.contains("&sp=r"), "{url}");
    }

    #[test]
    fn py_quote_matches_urllib() {
        // python: quote("a b/ä+&=?#%~_.-!*'()") == 'a%20b/%C3%A4%2B%26%3D%3F%23%25~_.-%21%2A%27%28%29'
        assert_eq!(
            py_quote("a b/ä+&=?#%~_.-!*'()"),
            "a%20b/%C3%A4%2B%26%3D%3F%23%25~_.-%21%2A%27%28%29"
        );
    }

    fn x_ms(pairs: &[(&str, &str)]) -> Vec<(String, String)> {
        pairs.iter().map(|(k, v)| (k.to_string(), v.to_string())).collect()
    }

    #[test]
    fn shared_key_matches_the_sdk_policy() {
        // python: SharedKeyCredentialPolicy(ACCOUNT, KEY).on_request(...) on the same requests.
        let key = decode_account_key(KEY).unwrap();
        let headers = x_ms(&[
            ("x-ms-version", "2026-10-06"),
            ("x-ms-date", "Thu, 29 Oct 2026 08:00:00 GMT"),
            ("x-ms-client-request-id", "abc"),
        ]);
        let sts = shared_key_string_to_sign(
            "PUT",
            &StandardHeaders {
                content_length: 0,
                content_type: None,
            },
            &headers,
            ACCOUNT,
            "/devstoreaccount1/c1",
            &[("restype", "container")],
        );
        assert_eq!(sign(&key, &sts), "JLY85qgMwq0UW3kULCuExW16jH59YFMywM6a8Mych8Y=");

        let headers = x_ms(&[
            ("x-ms-version", "2026-10-06"),
            ("x-ms-date", "Thu, 29 Oct 2026 08:00:00 GMT"),
            ("x-ms-client-request-id", "abc"),
            ("x-ms-blob-type", "BlockBlob"),
            ("x-ms-blob-content-type", "text/plain"),
            ("x-ms-meta-new_file", "true"),
            ("x-ms-meta-newfile", "x"),
            ("x-ms-meta-new-file", "y"),
            ("x-ms-meta-Type", "drift"),
        ]);
        let sts = shared_key_string_to_sign(
            "PUT",
            &StandardHeaders {
                content_length: 7,
                content_type: Some("application/octet-stream"),
            },
            &headers,
            ACCOUNT,
            "/devstoreaccount1/c1/dir/a%20b.txt",
            &[],
        );
        assert_eq!(sign(&key, &sts), "eANX5WI2LG0obLkD0SWwastCCOZiPFUx6kXvTxzjtj4=");
    }

    #[test]
    fn header_collation_ignores_dashes_until_a_tie() {
        let mut names = [
            "x-ms-meta-newfile",
            "x-ms-meta-new_file",
            "x-ms-meta-new-file",
            "x-ms-date",
            "x-ms-blob-type",
        ];
        names.sort_by(|a, b| compare_headers(a, b));
        assert_eq!(names[..2], ["x-ms-blob-type", "x-ms-date"]);
    }

    #[test]
    fn endpoint_forms() {
        assert_eq!(
            service_base("https://acct.blob.core.windows.net").unwrap(),
            "https://acct.blob.core.windows.net"
        );
        assert_eq!(
            service_base("https://acct.blob.core.windows.net/").unwrap(),
            "https://acct.blob.core.windows.net"
        );
        assert_eq!(
            service_base("http://127.0.0.1:10000/devstoreaccount1/").unwrap(),
            "http://127.0.0.1:10000/devstoreaccount1"
        );
        assert_eq!(
            service_base("acct.blob.core.windows.net").unwrap(),
            "https://acct.blob.core.windows.net"
        );
        assert!(service_base("http://").is_err());
    }

    #[test]
    fn retry_budget_matches_storage_retry_policy() {
        // Measured on azure-storage-blob 12.31.0 against a closed port:
        // retry_total 0/1/3/5 -> 1/2/4/4 attempts.
        for (total, attempts) in [(0, 1), (1, 2), (3, 4), (5, 4)] {
            let mut counters = RetryCounters::new(total);
            let mut made = 1;
            while counters.increment(RetryKind::Connect) {
                made += 1;
            }
            assert_eq!(made, attempts, "retry_total={total}");
        }
    }

    #[test]
    fn backoff_follows_exponential_retry() {
        for _ in 0..50 {
            let d1 = Backoff::SDK.delay(1).as_secs_f64();
            let d2 = Backoff::SDK.delay(2).as_secs_f64();
            assert!((15.0..21.0).contains(&d1), "{d1}");
            assert!((21.0..27.0).contains(&d2), "{d2}");
        }
    }

    #[test]
    fn lenient_key_decoding() {
        assert_eq!(decode_account_key("a2V5").unwrap(), b"key");
        assert_eq!(decode_account_key("a2V5!").unwrap(), b"key");
        assert_eq!(decode_account_key("a2V").unwrap_err(), "Incorrect padding");
    }

    #[test]
    fn error_text_matches_process_storage_error() {
        // python: str(e) of the ResourceExistsError raised by a second create_container.
        let body = "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>\n<Error>\n  <Code>ContainerAlreadyExists</Code>\n  <Message>The specified container already exists.\nRequestId:3020bf70-82b2-4ca5-96ab-d9fe843f0f05\nTime:2026-10-29T08:45:06.782Z</Message>\n</Error>";
        let mut headers = HeaderMap::new();
        headers.insert("content-type", HeaderValue::from_static("application/xml"));
        headers.insert("x-ms-error-code", HeaderValue::from_static("ContainerAlreadyExists"));
        let error = StorageError::from_reply(&Reply {
            status: 409,
            headers,
            body: body.as_bytes().to_vec(),
        });
        assert_eq!(error.class, ErrorClass::Exists);
        assert_eq!(
            error.text,
            "The specified container already exists.\nRequestId:3020bf70-82b2-4ca5-96ab-d9fe843f0f05\nTime:2026-10-29T08:45:06.782Z\nErrorCode:ContainerAlreadyExists\nContent: <?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>\n<Error>\n  <Code>ContainerAlreadyExists</Code>\n  <Message>The specified container already exists.\nRequestId:3020bf70-82b2-4ca5-96ab-d9fe843f0f05\nTime:2026-10-29T08:45:06.782Z</Message>\n</Error>"
        );
        // HEAD: no body, the code only in the header.
        let mut headers = HeaderMap::new();
        headers.insert("x-ms-error-code", HeaderValue::from_static("AuthorizationFailure"));
        let error = StorageError::from_reply(&Reply {
            status: 403,
            headers,
            body: Vec::new(),
        });
        assert_eq!(error.class, ErrorClass::Other);
        assert_eq!(
            error.text,
            "Operation returned an invalid status 'Forbidden'\nErrorCode:AuthorizationFailure"
        );
    }

    // --- Azurite ---------------------------------------------------------------

    fn azurite_url() -> Option<String> {
        std::env::var("KUMOSS_TEST_AZURITE_URL").ok().filter(|v| !v.is_empty())
    }

    fn container_name() -> String {
        format!("test-{}", &uuid::Uuid::new_v4().simple().to_string()[..12])
    }

    async fn storage() -> Option<StorageAccountObjectStorage> {
        let Some(endpoint) = azurite_url() else {
            eprintln!("KUMOSS_TEST_AZURITE_URL unset: skipping Azurite test");
            return None;
        };
        let storage =
            StorageAccountObjectStorage::new(AzureOptions::new(container_name(), ACCOUNT, endpoint, KEY, EXPIRY))
                .unwrap();
        storage.ensure_bucket().await.expect("ensure_bucket");
        Some(storage)
    }

    fn meta(pairs: &[(&str, &str)]) -> ObjectMetadata {
        pairs.iter().map(|(k, v)| (k.to_string(), v.to_string())).collect()
    }

    #[tokio::test]
    async fn azurite_ensure_bucket_is_idempotent() {
        let Some(storage) = storage().await else { return };
        storage.ensure_bucket().await.expect("second ensure_bucket");
    }

    #[tokio::test]
    async fn azurite_put_get_exists_delete() {
        let Some(storage) = storage().await else { return };
        storage
            .put("dir/a b.txt", b"payload".to_vec(), "text/plain", &meta(&[]))
            .await
            .unwrap();
        assert_eq!(storage.get("dir/a b.txt").await.unwrap(), b"payload");
        assert!(storage.exists("dir/a b.txt").await.unwrap());
        assert!(!storage.exists("not-here.txt").await.unwrap());
        storage.delete("dir/a b.txt").await.unwrap();
        storage.delete("dir/a b.txt").await.unwrap(); // second delete must not raise
        assert!(!storage.exists("dir/a b.txt").await.unwrap());
        storage
            .put("w.txt", b"one".to_vec(), "text/plain", &meta(&[]))
            .await
            .unwrap();
        storage
            .put("w.txt", b"two".to_vec(), "text/plain", &meta(&[]))
            .await
            .unwrap();
        assert_eq!(storage.get("w.txt").await.unwrap(), b"two");
        storage
            .put("empty.txt", Vec::new(), "text/plain", &meta(&[]))
            .await
            .unwrap();
        assert_eq!(storage.get("empty.txt").await.unwrap(), b"");
    }

    #[tokio::test]
    async fn azurite_get_missing_raises_object_not_found() {
        let Some(storage) = storage().await else { return };
        let err = storage.get("missing.txt").await.unwrap_err();
        assert_eq!(err.kind, ErrorKind::ObjectNotFound, "{err}");
        assert_eq!(err.code, 404);
        assert_eq!(
            err.message,
            format!("Object '{}/missing.txt' not found.", storage.container)
        );
    }

    #[tokio::test]
    async fn azurite_missing_container_reads_as_not_found() {
        let Some(endpoint) = azurite_url() else { return };
        let storage =
            StorageAccountObjectStorage::new(AzureOptions::new(container_name(), ACCOUNT, endpoint, KEY, EXPIRY))
                .unwrap();
        assert!(!storage.exists("k").await.unwrap());
        storage.delete("k").await.unwrap();
        assert_eq!(storage.get("k").await.unwrap_err().kind, ErrorKind::ObjectNotFound);
    }

    #[tokio::test]
    async fn azurite_sas_url_fetches_via_plain_http_with_metadata() {
        let Some(storage) = storage().await else { return };
        let key = "sessions/s/rounds/1/code_changes/vars-abc12345 ä+&=.tf";
        storage
            .put(
                key,
                b"variable \"a\" {}".to_vec(),
                "application/json",
                &meta(&[("type", "drift"), ("new_file", "true")]),
            )
            .await
            .unwrap();
        let url = storage.presigned_get_url(key, None).await.unwrap();
        let http = reqwest::Client::new();
        let response = http.get(&url).send().await.unwrap();
        assert_eq!(response.status(), 200, "{url}");
        let prefix = storage.metadata_header_prefix();
        let headers = response.headers().clone();
        assert_eq!(headers.get("content-type").unwrap(), "application/json");
        assert_eq!(headers.get(format!("{prefix}type")).unwrap(), "drift");
        assert_eq!(headers.get(format!("{prefix}new_file")).unwrap(), "true");
        assert_eq!(response.bytes().await.unwrap().as_ref(), b"variable \"a\" {}");
        let response = http.get(&url).header("Range", "bytes=0-0").send().await.unwrap();
        assert_eq!(response.status(), 206);
        assert_eq!(response.headers().get(format!("{prefix}type")).unwrap(), "drift");
        // A tampered signature is refused: the URL really is signed.
        let tampered = url.replace("sp=r", "sp=rw");
        assert_eq!(http.get(&tampered).send().await.unwrap().status(), 403);
    }

    #[tokio::test]
    async fn azurite_bad_key_is_a_500_with_the_service_text() {
        let Some(endpoint) = azurite_url() else { return };
        let mut opts = AzureOptions::new(container_name(), ACCOUNT, endpoint, "a2V5", EXPIRY);
        opts.max_attempts = 0;
        let storage = StorageAccountObjectStorage::new(opts).unwrap();
        let err = storage
            .put("x", b"x".to_vec(), "text/plain", &meta(&[]))
            .await
            .unwrap_err();
        assert_eq!(err.kind, ErrorKind::ObjectStorage, "{err}");
        eprintln!("put with a bad key: {}", err.message);
        assert!(err.message.starts_with(&format!(
            "Object storage put failed on '{}/x': Server failed to authenticate the request. Make sure the value of the Authorization header is formed correctly including the signature.\nRequestId:",
            storage.container
        )), "{}", err.message);
        assert!(
            err.message.contains("\nErrorCode:AuthorizationFailure\nContent: <?xml"),
            "{}",
            err.message
        );
        let err = storage.exists("x").await.unwrap_err();
        eprintln!("exists with a bad key: {}", err.message);
        assert_eq!(err.kind, ErrorKind::ObjectStorage);
    }

    #[tokio::test]
    async fn unreachable_endpoint_raises_unavailable() {
        // Nothing listens on port 9: needs no emulator.
        let mut opts = AzureOptions::new("c", ACCOUNT, "http://127.0.0.1:9/devstoreaccount1", KEY, EXPIRY);
        opts.connect_timeout = 0.2;
        opts.read_timeout = 0.2;
        opts.max_attempts = 0;
        let down = StorageAccountObjectStorage::new(opts).unwrap();
        let err = down
            .put("x.txt", b"x".to_vec(), "text/plain", &meta(&[]))
            .await
            .unwrap_err();
        assert_eq!(err.kind, ErrorKind::ObjectStorageUnavailable, "{err}");
        assert_eq!(err.code, 503);
        assert_eq!(err.message, "Object store unreachable during put on 'c/x.txt'.");
        let err = down.ensure_bucket().await.unwrap_err();
        assert_eq!(err.message, "Object store unreachable during ensure_bucket on 'c'.");
    }

    #[tokio::test]
    async fn retries_sleep_between_attempts() {
        // retry_total 2 with a tiny backoff: 3 connect attempts, then 503.
        let mut opts = AzureOptions::new("c", ACCOUNT, "http://127.0.0.1:9/devstoreaccount1", KEY, EXPIRY);
        opts.connect_timeout = 0.2;
        opts.max_attempts = 2;
        let mut down = StorageAccountObjectStorage::new(opts).unwrap();
        down.backoff = Backoff {
            initial: 0.05,
            base: 0.0,
            jitter: 0.0,
        };
        let started = std::time::Instant::now();
        let err = down.exists("x").await.unwrap_err();
        assert_eq!(err.kind, ErrorKind::ObjectStorageUnavailable);
        assert!(
            started.elapsed() >= Duration::from_millis(100),
            "{:?}",
            started.elapsed()
        );
    }

    #[tokio::test]
    async fn server_errors_are_retried_then_500() {
        // python (ExponentialRetry(retry_total=3), zero backoff) against a server
        // always answering 503 SlowDown: 4 requests, then this text.
        use wiremock::{Mock, MockServer, ResponseTemplate, matchers::any};
        let body = "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<Error><Code>SlowDown</Code><Message>Please reduce your request rate.</Message></Error>";
        let server = MockServer::start().await;
        Mock::given(any())
            .respond_with(ResponseTemplate::new(503).set_body_raw(body, "application/xml"))
            .mount(&server)
            .await;
        let opts = AzureOptions::new("c", ACCOUNT, format!("{}/devstoreaccount1", server.uri()), KEY, EXPIRY);
        let mut storage = StorageAccountObjectStorage::new(opts).unwrap();
        storage.backoff = Backoff {
            initial: 0.0,
            base: 0.0,
            jitter: 0.0,
        };
        let err = storage
            .put("k", b"x".to_vec(), "text/plain", &meta(&[]))
            .await
            .unwrap_err();
        assert_eq!(server.received_requests().await.unwrap().len(), 4);
        assert_eq!(err.kind, ErrorKind::ObjectStorage);
        assert_eq!(
            err.message,
            format!(
                "Object storage put failed on 'c/k': Please reduce your request rate.\nErrorCode:SlowDown\nContent: {body}"
            )
        );
    }

    #[tokio::test]
    async fn empty_key_is_rejected_like_get_blob_client() {
        let storage = StorageAccountObjectStorage::new(AzureOptions::new(
            "c",
            ACCOUNT,
            "http://127.0.0.1:9/devstoreaccount1",
            KEY,
            EXPIRY,
        ))
        .unwrap();
        let err = storage.get("").await.unwrap_err();
        assert_eq!(
            err.message,
            "Object storage get failed on 'c': Please specify a container name and blob name."
        );
    }
}
