// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

//! S3-API adapter over `aws-sdk-s3` (RustFS, MinIO, AWS S3).

use std::collections::HashMap;
use std::error::Error as StdError;
use std::sync::atomic::{AtomicU32, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use async_trait::async_trait;
use aws_config::BehaviorVersion;
use aws_sdk_s3::Client;
use aws_sdk_s3::config::interceptors::BeforeTransmitInterceptorContextRef;
use aws_sdk_s3::config::retry::RetryConfig;
use aws_sdk_s3::config::timeout::TimeoutConfig;
use aws_sdk_s3::config::{ConfigBag, Credentials, Intercept, Region, RuntimeComponents, StalledStreamProtectionConfig};
use aws_sdk_s3::error::{BoxError, ProvideErrorMetadata, SdkError};
use aws_sdk_s3::presigning::PresigningConfig;
use aws_sdk_s3::primitives::ByteStream;
use aws_sdk_s3::types::{BucketLocationConstraint, CreateBucketConfiguration};

use crate::domain::ports::{ObjectMetadata, ObjectStorage};
use crate::shared::error::{AppError, AppResult, ErrorKind};

type HttpResponse = aws_sdk_s3::config::http::HttpResponse;

/// Error codes botocore reports for a missing key or bucket. `404` is what
/// an empty-bodied (HEAD) not-found response yields.
const NOT_FOUND_CODES: [&str; 3] = ["404", "NoSuchKey", "NoSuchBucket"];
const ALREADY_OWNED_CODES: [&str; 2] = ["BucketAlreadyOwnedByYou", "BucketAlreadyExists"];
const METADATA_HEADER_PREFIX: &str = "x-amz-meta-";

/// botocore's `ParamValidationError` text for an empty `Key`.
const EMPTY_KEY_ERROR: &str =
    "Parameter validation failed:\nInvalid length for parameter Key, value: 0, valid min length: 1";

/// Construction parameters of [`S3ObjectStorage`].
#[derive(Debug, Clone)]
pub struct S3Options {
    /// Bucket holding every object this adapter touches.
    pub bucket: String,
    /// AWS region (drives the default endpoint when `endpoint_url` is None).
    pub region: String,
    /// Custom S3 endpoint for SDK calls; None means the AWS regional default.
    pub endpoint_url: Option<String>,
    /// Host presigned URLs are signed against; None or equal to
    /// `endpoint_url` reuses the main client.
    pub public_endpoint_url: Option<String>,
    /// Static credentials; None/empty defers to the default credential chain
    /// (env vars, profile, IAM role).
    pub access_key: Option<String>,
    /// Counterpart of `access_key`.
    pub secret_key: Option<String>,
    /// Default validity of presigned GET URLs.
    pub presign_expiry_seconds: u64,
    /// Path-style addressing (custom endpoints) vs virtual-hosted (AWS).
    pub force_path_style: bool,
    /// Seconds to establish a connection.
    pub connect_timeout: f64,
    /// Seconds to wait on a response.
    pub read_timeout: f64,
    /// botocore client-config `max_attempts`: the number of *retries* in
    /// standard mode, so a request is tried at most `max_attempts + 1` times.
    pub max_attempts: u32,
}

impl S3Options {
    /// The Python constructor's defaults: path-style, 3s/10s timeouts, 3 attempts.
    pub fn new(bucket: impl Into<String>, region: impl Into<String>, presign_expiry_seconds: u64) -> Self {
        Self {
            bucket: bucket.into(),
            region: region.into(),
            endpoint_url: None,
            public_endpoint_url: None,
            access_key: None,
            secret_key: None,
            presign_expiry_seconds,
            force_path_style: true,
            connect_timeout: 3.0,
            read_timeout: 10.0,
            max_attempts: 3,
        }
    }
}

/// S3-API adapter (RustFS, MinIO, AWS S3).
///
/// Two clients exist because SigV4 binds the Host header: `client` talks to
/// the store on the internal endpoint, while URLs handed to the browser must
/// be signed against the host the browser will fetch, so `presign` is built
/// on `public_endpoint_url` (it never touches the network). With no custom
/// endpoints (AWS) a single client on the regional default serves both roles.
#[derive(Debug, Clone)]
pub struct S3ObjectStorage {
    bucket: String,
    region: String,
    endpoint_url: Option<String>,
    presign_expiry: u64,
    /// Total attempts per request (botocore's `total_max_attempts`).
    total_attempts: u32,
    read_timeout: Duration,
    client: Client,
    presign: Client,
}

fn seconds(value: f64) -> Duration {
    Duration::try_from_secs_f64(value.max(0.0)).unwrap_or(Duration::MAX)
}

fn non_empty(value: &Option<String>) -> Option<&str> {
    value.as_deref().filter(|v| !v.is_empty())
}

impl S3ObjectStorage {
    /// Build both clients. Loads the shared AWS configuration (env, profile)
    /// like boto3 does; no request is sent.
    pub async fn new(opts: S3Options) -> Self {
        // botocore turns client-config `max_attempts` (retries) into
        // `total_max_attempts = max_attempts + 1`.
        let total_attempts = opts.max_attempts.saturating_add(1);
        let mut loader = aws_config::defaults(BehaviorVersion::latest())
            .region(Region::new(opts.region.clone()))
            .retry_config(RetryConfig::standard().with_max_attempts(total_attempts))
            .timeout_config(
                TimeoutConfig::builder()
                    .connect_timeout(seconds(opts.connect_timeout))
                    .read_timeout(seconds(opts.read_timeout))
                    .build(),
            )
            // botocore has no throughput watchdog; the read timeout bounds stalls.
            .stalled_stream_protection(StalledStreamProtectionConfig::disabled());
        if let (Some(access_key), Some(secret_key)) = (non_empty(&opts.access_key), non_empty(&opts.secret_key)) {
            loader = loader.credentials_provider(Credentials::new(access_key, secret_key, None, None, "kumoss-static"));
        }
        let shared = loader.load().await;
        let build = |endpoint: Option<&str>| {
            let mut builder = aws_sdk_s3::config::Builder::from(&shared).force_path_style(opts.force_path_style);
            if let Some(endpoint) = endpoint {
                builder = builder.endpoint_url(endpoint);
            }
            Client::from_conf(builder.build())
        };
        let client = build(opts.endpoint_url.as_deref());
        let presign = match non_empty(&opts.public_endpoint_url) {
            Some(public) if Some(public) != opts.endpoint_url.as_deref() => build(Some(public)),
            _ => client.clone(),
        };
        Self {
            bucket: opts.bucket,
            region: opts.region,
            endpoint_url: opts.endpoint_url,
            presign_expiry: opts.presign_expiry_seconds,
            total_attempts,
            read_timeout: seconds(opts.read_timeout),
            client,
            presign,
        }
    }

    pub fn bucket(&self) -> &str {
        &self.bucket
    }

    fn target(&self, key: &str) -> String {
        if key.is_empty() {
            self.bucket.clone()
        } else {
            format!("{}/{}", self.bucket, key)
        }
    }

    /// Map any SDK failure onto the domain errors (port contract), logging
    /// the same line the Python adapter did.
    fn translate(&self, failure: Failure, op: &str, key: &str) -> AppError {
        let target = self.target(key);
        let text = failure.text();
        tracing::error!("Object storage {op} failed on '{target}': {text}");
        match failure {
            Failure::Unreachable(_) => AppError::kind(
                ErrorKind::ObjectStorageUnavailable,
                format!("Object store unreachable during {op} on '{target}'."),
                503,
            ),
            Failure::Client { code, .. } if NOT_FOUND_CODES.contains(&code.as_str()) => {
                AppError::kind(ErrorKind::ObjectNotFound, format!("Object '{target}' not found."), 404)
            }
            _ => AppError::kind(
                ErrorKind::ObjectStorage,
                format!("Object storage {op} failed on '{target}': {text}"),
                500,
            ),
        }
    }

    fn classify<E>(&self, error: SdkError<E, HttpResponse>, operation: &str, trace: &CallTrace) -> Failure
    where
        E: ProvideErrorMetadata + StdError + Send + Sync + 'static,
    {
        classify(error, operation, trace, self.total_attempts)
    }

    async fn ensure_bucket_inner(&self) -> Result<(), Failure> {
        let trace = CallTrace::new();
        match self
            .client
            .head_bucket()
            .bucket(&self.bucket)
            .customize()
            .interceptor(trace.interceptor())
            .send()
            .await
        {
            Ok(_) => return Ok(()),
            Err(e) => match self.classify(e, "HeadBucket", &trace) {
                Failure::Client { code, .. } if NOT_FOUND_CODES.contains(&code.as_str()) => {}
                other => return Err(other),
            },
        }
        let mut request = self.client.create_bucket().bucket(&self.bucket);
        if self.endpoint_url.is_none() && self.region != "us-east-1" {
            // Only real AWS wants the location constraint.
            request = request.create_bucket_configuration(
                CreateBucketConfiguration::builder()
                    .location_constraint(BucketLocationConstraint::from(self.region.as_str()))
                    .build(),
            );
        }
        let trace = CallTrace::new();
        match request.customize().interceptor(trace.interceptor()).send().await {
            Ok(_) => Ok(()),
            Err(e) => match self.classify(e, "CreateBucket", &trace) {
                // Two replicas racing the same boot is not an error.
                Failure::Client { code, .. } if ALREADY_OWNED_CODES.contains(&code.as_str()) => Ok(()),
                other => Err(other),
            },
        }
    }

    async fn put_inner(
        &self,
        key: &str,
        data: Vec<u8>,
        content_type: &str,
        metadata: &ObjectMetadata,
    ) -> Result<(), Failure> {
        if key.is_empty() {
            return Err(Failure::Other(EMPTY_KEY_ERROR.into()));
        }
        let metadata: HashMap<String, String> = metadata.iter().map(|(k, v)| (k.clone(), v.clone())).collect();
        let trace = CallTrace::new();
        self.client
            .put_object()
            .bucket(&self.bucket)
            .key(key)
            .body(ByteStream::from(data))
            .content_type(content_type)
            .set_metadata(Some(metadata))
            .customize()
            .interceptor(trace.interceptor())
            .send()
            .await
            .map(|_| ())
            .map_err(|e| self.classify(e, "PutObject", &trace))
    }

    async fn get_inner(&self, key: &str) -> Result<Vec<u8>, Failure> {
        if key.is_empty() {
            return Err(Failure::Other(EMPTY_KEY_ERROR.into()));
        }
        let trace = CallTrace::new();
        let output = self
            .client
            .get_object()
            .bucket(&self.bucket)
            .key(key)
            .customize()
            .interceptor(trace.interceptor())
            .send()
            .await
            .map_err(|e| self.classify(e, "GetObject", &trace))?;
        // The body read is network IO too: each read is bounded by the read
        // timeout, as urllib3's socket timeout bounds botocore's body read.
        let mut body = output.body;
        let mut data = Vec::new();
        loop {
            match tokio::time::timeout(self.read_timeout, body.next()).await {
                Err(_) => {
                    return Err(Failure::Unreachable(format!(
                        "Read timeout on endpoint URL: \"{}\"",
                        trace.url()
                    )));
                }
                Ok(None) => return Ok(data),
                Ok(Some(Ok(chunk))) => data.extend_from_slice(&chunk),
                Ok(Some(Err(e))) => {
                    return Err(Failure::Other(format!(
                        "An error occurred while reading from response stream: {}",
                        error_chain(&e)
                    )));
                }
            }
        }
    }

    async fn exists_inner(&self, key: &str) -> Result<bool, Failure> {
        if key.is_empty() {
            return Err(Failure::Other(EMPTY_KEY_ERROR.into()));
        }
        let trace = CallTrace::new();
        match self
            .client
            .head_object()
            .bucket(&self.bucket)
            .key(key)
            .customize()
            .interceptor(trace.interceptor())
            .send()
            .await
        {
            Ok(_) => Ok(true),
            Err(e) => match self.classify(e, "HeadObject", &trace) {
                Failure::Client { code, .. } if NOT_FOUND_CODES.contains(&code.as_str()) => Ok(false),
                other => Err(other),
            },
        }
    }

    async fn delete_inner(&self, key: &str) -> Result<(), Failure> {
        if key.is_empty() {
            return Err(Failure::Other(EMPTY_KEY_ERROR.into()));
        }
        // S3 returns 204 for absent keys: naturally idempotent.
        let trace = CallTrace::new();
        self.client
            .delete_object()
            .bucket(&self.bucket)
            .key(key)
            .customize()
            .interceptor(trace.interceptor())
            .send()
            .await
            .map(|_| ())
            .map_err(|e| self.classify(e, "DeleteObject", &trace))
    }

    async fn presign_inner(&self, key: &str, expires_in: Option<u64>) -> Result<String, Failure> {
        if key.is_empty() {
            return Err(Failure::Other(EMPTY_KEY_ERROR.into()));
        }
        // `expires_in or default`: 0 falls back to the default too.
        let expires = expires_in.filter(|s| *s != 0).unwrap_or(self.presign_expiry);
        let config =
            PresigningConfig::expires_in(Duration::from_secs(expires)).map_err(|e| Failure::Other(error_chain(&e)))?;
        let trace = CallTrace::new();
        self.presign
            .get_object()
            .bucket(&self.bucket)
            .key(key)
            .presigned(config)
            .await
            .map(|request| request.uri().to_string())
            .map_err(|e| self.classify(e, "GetObject", &trace))
    }
}

#[async_trait]
impl ObjectStorage for S3ObjectStorage {
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
            .await
            .map_err(|f| self.translate(f, "presign", key))
    }
}

/// An SDK failure, classified the way botocore's exception types are.
#[derive(Debug)]
enum Failure {
    /// `EndpointConnectionError` / `ConnectTimeoutError` / `ReadTimeoutError`.
    Unreachable(String),
    /// `ClientError`: `code` is botocore's error code, `text` its `str()`.
    Client { code: String, text: String },
    /// Anything else, with its `str()`.
    Other(String),
}

impl Failure {
    fn text(&self) -> &str {
        match self {
            Failure::Unreachable(t) | Failure::Other(t) => t,
            Failure::Client { text, .. } => text,
        }
    }
}

/// Per-call record of how many attempts were transmitted and to which URL,
/// for botocore's error texts (`reached max retries`, endpoint URL).
#[derive(Debug, Default)]
struct CallTrace {
    attempts: AtomicU32,
    url: Mutex<Option<String>>,
}

impl CallTrace {
    fn new() -> Arc<Self> {
        Arc::new(Self::default())
    }

    fn interceptor(self: &Arc<Self>) -> TraceInterceptor {
        TraceInterceptor(Arc::clone(self))
    }

    fn attempts(&self) -> u32 {
        self.attempts.load(Ordering::SeqCst)
    }

    /// The last request URL without the Rust SDK's `x-id` marker, which
    /// botocore does not send.
    fn url(&self) -> String {
        let url = self
            .url
            .lock()
            .map(|u| u.clone().unwrap_or_default())
            .unwrap_or_default();
        let Some((base, query)) = url.split_once('?') else {
            return url;
        };
        let kept: Vec<&str> = query.split('&').filter(|p| !p.starts_with("x-id=")).collect();
        if kept.is_empty() {
            base.to_string()
        } else {
            format!("{base}?{}", kept.join("&"))
        }
    }
}

#[derive(Debug)]
struct TraceInterceptor(Arc<CallTrace>);

impl Intercept for TraceInterceptor {
    fn name(&self) -> &'static str {
        "KumossCallTrace"
    }

    fn read_before_transmit(
        &self,
        context: &BeforeTransmitInterceptorContextRef<'_>,
        _runtime_components: &RuntimeComponents,
        _cfg: &mut ConfigBag,
    ) -> Result<(), BoxError> {
        self.0.attempts.fetch_add(1, Ordering::SeqCst);
        if let Ok(mut url) = self.0.url.lock() {
            *url = Some(context.request().uri().to_string());
        }
        Ok(())
    }
}

/// `str(e)` chain of a Rust error: each distinct source appended.
fn error_chain(error: &(dyn StdError + 'static)) -> String {
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

/// Whether the failure happened while establishing the connection (refused,
/// unresolvable, unroutable): botocore's `EndpointConnectionError`.
fn is_connect_failure(error: &(dyn StdError + 'static)) -> bool {
    let mut next = Some(error);
    while let Some(e) = next {
        if e.to_string().starts_with("client error (Connect)") {
            return true;
        }
        if let Some(io) = e.downcast_ref::<std::io::Error>() {
            use std::io::ErrorKind as K;
            if matches!(
                io.kind(),
                K::ConnectionRefused | K::HostUnreachable | K::NetworkUnreachable | K::AddrNotAvailable
            ) {
                return true;
            }
        }
        next = e.source();
    }
    false
}

/// The `(code, message)` botocore parses out of an error response: an empty
/// (HEAD) body yields the HTTP status and its reason phrase.
fn botocore_error<E: ProvideErrorMetadata>(error: &E, raw: &HttpResponse) -> (String, String) {
    let status = raw.status().as_u16();
    let reason = http_reason(status);
    let empty_body = raw.body().bytes().is_none_or(|b| b.is_empty());
    if empty_body {
        return (status.to_string(), reason.to_string());
    }
    match error.code() {
        Some(code) => (code.to_string(), error.message().unwrap_or("Unknown").to_string()),
        None => (status.to_string(), reason.to_string()),
    }
}

/// `http.client.responses[status]` for the statuses an S3 store returns.
fn http_reason(status: u16) -> &'static str {
    match status {
        400 => "Bad Request",
        401 => "Unauthorized",
        403 => "Forbidden",
        404 => "Not Found",
        405 => "Method Not Allowed",
        409 => "Conflict",
        411 => "Length Required",
        412 => "Precondition Failed",
        416 => "Requested Range Not Satisfiable",
        500 => "Internal Server Error",
        501 => "Not Implemented",
        502 => "Bad Gateway",
        503 => "Service Unavailable",
        504 => "Gateway Timeout",
        _ => "",
    }
}

fn classify<E>(error: SdkError<E, HttpResponse>, operation: &str, trace: &CallTrace, total_attempts: u32) -> Failure
where
    E: ProvideErrorMetadata + StdError + Send + Sync + 'static,
{
    let url = trace.url();
    match error {
        SdkError::ServiceError(context) => {
            let (code, message) = botocore_error(context.err(), context.raw());
            let attempts = trace.attempts();
            // botocore flags MaxAttemptsReached whenever the last attempt hit the budget.
            let retry_info = if attempts >= total_attempts && attempts > 0 {
                format!(" (reached max retries: {})", attempts - 1)
            } else {
                String::new()
            };
            let text =
                format!("An error occurred ({code}) when calling the {operation} operation{retry_info}: {message}");
            Failure::Client { code, text }
        }
        SdkError::TimeoutError(_) => Failure::Unreachable(format!("Read timeout on endpoint URL: \"{url}\"")),
        SdkError::DispatchFailure(failure) => {
            let chain: Option<&(dyn StdError + 'static)> =
                failure.as_connector_error().map(|c| c as &(dyn StdError + 'static));
            if failure.is_timeout() {
                let connect = chain.is_some_and(|c| error_chain(c).contains("HTTP connect timeout"));
                let kind = if connect { "Connect" } else { "Read" };
                Failure::Unreachable(format!("{kind} timeout on endpoint URL: \"{url}\""))
            } else if chain.is_some_and(is_connect_failure) {
                Failure::Unreachable(format!("Could not connect to the endpoint URL: \"{url}\""))
            } else if failure.is_io() {
                // botocore's ConnectionClosedError: not an availability error.
                Failure::Other(format!(
                    "Connection was closed before we received a valid response from endpoint URL: \"{url}\"."
                ))
            } else {
                Failure::Other(chain.map(error_chain).unwrap_or_else(|| format!("{failure:?}")))
            }
        }
        other => Failure::Other(error_chain(&other)),
    }
}

#[cfg(test)]
mod tests {
    //! Behavioral tests against a real RustFS. They run when
    //! `KUMOSS_TEST_RUSTFS_URL` points at one, e.g.:
    //!
    //! ```text
    //! docker run -d --rm -p 19000:9000 rustfs/rustfs:latest
    //! KUMOSS_TEST_RUSTFS_URL=http://127.0.0.1:19000 cargo test --lib storage
    //! ```
    //!
    //! Default credentials are rustfsadmin/rustfsadmin
    //! (`KUMOSS_TEST_RUSTFS_ACCESS_KEY` / `KUMOSS_TEST_RUSTFS_SECRET_KEY`).

    use super::*;

    const EXPIRY: u64 = 172_800;

    fn rustfs_url() -> Option<String> {
        std::env::var("KUMOSS_TEST_RUSTFS_URL").ok().filter(|v| !v.is_empty())
    }

    fn env_or(name: &str, default: &str) -> String {
        std::env::var(name)
            .ok()
            .filter(|v| !v.is_empty())
            .unwrap_or_else(|| default.to_string())
    }

    fn options(endpoint: &str, bucket: &str) -> S3Options {
        let mut opts = S3Options::new(bucket, "us-east-1", EXPIRY);
        opts.endpoint_url = Some(endpoint.to_string());
        opts.public_endpoint_url = Some(endpoint.to_string());
        opts.access_key = Some(env_or("KUMOSS_TEST_RUSTFS_ACCESS_KEY", "rustfsadmin"));
        opts.secret_key = Some(env_or("KUMOSS_TEST_RUSTFS_SECRET_KEY", "rustfsadmin"));
        opts
    }

    fn unique_bucket() -> String {
        format!("test-{}", &uuid::Uuid::new_v4().simple().to_string()[..12])
    }

    /// Throwaway bucket per test; returns None (test skipped) without RustFS.
    async fn storage() -> Option<(S3ObjectStorage, String)> {
        let Some(endpoint) = rustfs_url() else {
            eprintln!("KUMOSS_TEST_RUSTFS_URL unset: skipping RustFS test");
            return None;
        };
        let storage = S3ObjectStorage::new(options(&endpoint, &unique_bucket())).await;
        storage.ensure_bucket().await.expect("ensure_bucket");
        Some((storage, endpoint))
    }

    /// Raw cleanup: the port deliberately has no bucket delete.
    async fn cleanup(storage: &S3ObjectStorage) {
        let client = &storage.client;
        if let Ok(listed) = client.list_objects_v2().bucket(&storage.bucket).send().await {
            for object in listed.contents() {
                if let Some(key) = object.key() {
                    let _ = client.delete_object().bucket(&storage.bucket).key(key).send().await;
                }
            }
        }
        let _ = client.delete_bucket().bucket(&storage.bucket).send().await;
    }

    fn meta(pairs: &[(&str, &str)]) -> ObjectMetadata {
        pairs.iter().map(|(k, v)| (k.to_string(), v.to_string())).collect()
    }

    #[test]
    fn metadata_prefix_is_amazon() {
        assert_eq!(METADATA_HEADER_PREFIX, "x-amz-meta-");
    }

    #[tokio::test]
    async fn presign_uses_public_endpoint_and_default_expiry() {
        // Pure local computation: no store needed.
        let mut opts = options("http://object-storage:9000", "bkt");
        opts.public_endpoint_url = Some("http://localhost:9000".into());
        let storage = S3ObjectStorage::new(opts).await;
        let url = storage.presigned_get_url("some/key.txt", None).await.unwrap();
        assert!(url.starts_with("http://localhost:9000/bkt/some/key.txt?"), "{url}");
        assert!(url.contains("X-Amz-Signature="), "{url}");
        assert!(url.contains(&format!("X-Amz-Expires={EXPIRY}")), "{url}");
        let url = storage.presigned_get_url("some/key.txt", Some(600)).await.unwrap();
        assert!(url.contains("X-Amz-Expires=600"), "{url}");
        let url = storage.presigned_get_url("some/key.txt", Some(0)).await.unwrap();
        assert!(url.contains(&format!("X-Amz-Expires={EXPIRY}")), "{url}");
    }

    #[tokio::test]
    async fn empty_key_is_a_parameter_validation_error() {
        let storage = S3ObjectStorage::new(options("http://127.0.0.1:9", "bkt")).await;
        let err = storage.get("").await.unwrap_err();
        assert_eq!(err.kind, ErrorKind::ObjectStorage);
        assert_eq!(
            err.message,
            format!("Object storage get failed on 'bkt': {EMPTY_KEY_ERROR}")
        );
    }

    #[tokio::test]
    async fn unreachable_endpoint_raises_unavailable() {
        // Nothing listens on port 9: needs no store at all.
        let mut opts = options("http://127.0.0.1:9", "bkt");
        opts.connect_timeout = 0.2;
        opts.read_timeout = 0.2;
        opts.max_attempts = 0;
        let down = S3ObjectStorage::new(opts).await;
        let err = down
            .put("x.txt", b"x".to_vec(), "text/plain", &meta(&[]))
            .await
            .unwrap_err();
        assert_eq!(err.kind, ErrorKind::ObjectStorageUnavailable, "{err}");
        assert_eq!(err.code, 503);
        assert_eq!(err.message, "Object store unreachable during put on 'bkt/x.txt'.");
        let err = down.ensure_bucket().await.unwrap_err();
        assert_eq!(err.message, "Object store unreachable during ensure_bucket on 'bkt'.");
        // The logged text is botocore's EndpointConnectionError.
        match down.put_inner("x.txt", b"x".to_vec(), "text/plain", &meta(&[])).await {
            Err(Failure::Unreachable(text)) => {
                assert_eq!(
                    text,
                    "Could not connect to the endpoint URL: \"http://127.0.0.1:9/bkt/x.txt\""
                )
            }
            other => panic!("{other:?}"),
        }
    }

    #[tokio::test]
    async fn connect_timeout_raises_unavailable() {
        // A non-routable address: the connect attempt times out.
        let mut opts = options("http://10.255.255.1:9000", "bkt");
        opts.connect_timeout = 0.2;
        opts.max_attempts = 0;
        let down = S3ObjectStorage::new(opts).await;
        let err = down.exists("x.txt").await.unwrap_err();
        assert_eq!(err.kind, ErrorKind::ObjectStorageUnavailable, "{err}");
        match down.exists_inner("x.txt").await {
            Err(Failure::Unreachable(text)) => assert!(
                text == "Connect timeout on endpoint URL: \"http://10.255.255.1:9000/bkt/x.txt\""
                    || text.starts_with("Could not connect to the endpoint URL:"),
                "{text}"
            ),
            other => panic!("{other:?}"),
        }
    }

    const SLOW_DOWN: &str = "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<Error><Code>SlowDown</Code><Message>Please reduce your request rate.</Message></Error>";

    #[tokio::test]
    async fn retryable_errors_use_max_attempts_as_retries() {
        // python (boto3, retries={"max_attempts": 3, "mode": "standard"}) against a
        // server always answering 503 SlowDown: 4 requests, then this text.
        use wiremock::{Mock, MockServer, ResponseTemplate, matchers::any};
        let server = MockServer::start().await;
        Mock::given(any())
            .respond_with(ResponseTemplate::new(503).set_body_raw(SLOW_DOWN, "application/xml"))
            .mount(&server)
            .await;
        let storage = S3ObjectStorage::new(options(&server.uri(), "b")).await;
        let err = storage
            .put("k", b"x".to_vec(), "text/plain", &meta(&[]))
            .await
            .unwrap_err();
        assert_eq!(server.received_requests().await.unwrap().len(), 4);
        assert_eq!(err.kind, ErrorKind::ObjectStorage);
        assert_eq!(
            err.message,
            "Object storage put failed on 'b/k': An error occurred (SlowDown) when calling the PutObject operation (reached max retries: 3): Please reduce your request rate."
        );
    }

    #[tokio::test]
    async fn rustfs_ensure_bucket_is_idempotent() {
        let Some((storage, _)) = storage().await else { return };
        storage.ensure_bucket().await.expect("second ensure_bucket");
        cleanup(&storage).await;
    }

    #[tokio::test]
    async fn rustfs_put_get_exists_delete() {
        let Some((storage, _)) = storage().await else { return };
        storage
            .put("dir/a.txt", b"payload".to_vec(), "text/plain", &meta(&[]))
            .await
            .unwrap();
        assert_eq!(storage.get("dir/a.txt").await.unwrap(), b"payload");
        assert!(storage.exists("dir/a.txt").await.unwrap());
        assert!(!storage.exists("not-here.txt").await.unwrap());
        storage.delete("dir/a.txt").await.unwrap();
        storage.delete("dir/a.txt").await.unwrap(); // second delete must not raise
        assert!(!storage.exists("dir/a.txt").await.unwrap());
        // Last write wins.
        storage
            .put("w.txt", b"one".to_vec(), "text/plain", &meta(&[]))
            .await
            .unwrap();
        storage
            .put("w.txt", b"two".to_vec(), "text/plain", &meta(&[]))
            .await
            .unwrap();
        assert_eq!(storage.get("w.txt").await.unwrap(), b"two");
        // Empty body round trip.
        storage
            .put("empty.txt", Vec::new(), "text/plain", &meta(&[]))
            .await
            .unwrap();
        assert_eq!(storage.get("empty.txt").await.unwrap(), b"");
        cleanup(&storage).await;
    }

    #[tokio::test]
    async fn rustfs_get_missing_raises_object_not_found() {
        let Some((storage, _)) = storage().await else { return };
        let err = storage.get("missing.txt").await.unwrap_err();
        assert_eq!(err.kind, ErrorKind::ObjectNotFound, "{err}");
        assert_eq!(err.code, 404);
        assert_eq!(
            err.message,
            format!("Object '{}/missing.txt' not found.", storage.bucket)
        );
        cleanup(&storage).await;
    }

    #[tokio::test]
    async fn rustfs_missing_bucket_reads_as_not_found() {
        let Some(endpoint) = rustfs_url() else { return };
        let storage = S3ObjectStorage::new(options(&endpoint, &unique_bucket())).await;
        assert!(!storage.exists("k").await.unwrap());
        let err = storage.get("k").await.unwrap_err();
        assert_eq!(err.kind, ErrorKind::ObjectNotFound, "{err}");
    }

    #[tokio::test]
    async fn rustfs_presigned_get_fetches_via_plain_http_with_metadata() {
        let Some((storage, endpoint)) = storage().await else {
            return;
        };
        let key = "sessions/s/rounds/1/code_changes/vars-abc12345 ä.tf";
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
        assert!(url.starts_with(&format!("{endpoint}/{}/", storage.bucket)), "{url}");
        let http = reqwest::Client::new();
        let response = http.get(&url).send().await.unwrap();
        assert_eq!(response.status(), 200);
        let prefix = storage.metadata_header_prefix();
        let headers = response.headers().clone();
        assert_eq!(headers.get("content-type").unwrap(), "application/json");
        assert_eq!(headers.get(format!("{prefix}type")).unwrap(), "drift");
        assert_eq!(headers.get(format!("{prefix}new_file")).unwrap(), "true");
        assert_eq!(response.bytes().await.unwrap().as_ref(), b"variable \"a\" {}");
        // Ranged read keeps the metadata (the web client's plan-type probe).
        let response = http.get(&url).header("Range", "bytes=0-0").send().await.unwrap();
        assert_eq!(response.status(), 206);
        assert_eq!(response.headers().get(format!("{prefix}type")).unwrap(), "drift");
        cleanup(&storage).await;
    }

    #[tokio::test]
    async fn rustfs_bad_credentials_raise_the_botocore_client_error_text() {
        let Some(endpoint) = rustfs_url() else { return };
        let bucket = unique_bucket();
        let mut opts = options(&endpoint, &bucket);
        opts.secret_key = Some("wrong-secret".into());
        let storage = S3ObjectStorage::new(opts).await;
        let err = storage
            .put("k.txt", b"x".to_vec(), "text/plain", &meta(&[]))
            .await
            .unwrap_err();
        assert_eq!(err.kind, ErrorKind::ObjectStorage, "{err}");
        assert_eq!(err.code, 500);
        eprintln!("put with bad credentials: {}", err.message);
        assert_eq!(
            err.message,
            format!(
                "Object storage put failed on '{bucket}/k.txt': An error occurred (SignatureDoesNotMatch) when calling the PutObject operation: The request signature we calculated does not match the signature you provided. Check your AWS secret access key and signing method. For more information, see REST Authentication and SOAP Authentication for details."
            )
        );
        let err = storage.exists("k.txt").await.unwrap_err();
        eprintln!("exists with bad credentials: {}", err.message);
        assert_eq!(
            err.message,
            format!(
                "Object storage exists failed on '{bucket}/k.txt': An error occurred (403) when calling the HeadObject operation: Forbidden"
            )
        );
    }
}
