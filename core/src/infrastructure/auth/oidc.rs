// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

//! OIDC bearer-token validation against the configured issuer.
//!
//! This is a behavioural port of the Python core's validator, which used
//! PyJWT 2.15 (`PyJWKClient` + `jwt.decode`). Authentication must accept
//! exactly the tokens the Python service accepted, so the PyJWT pipeline is
//! reproduced step by step, including the parts of CPython it leans on:
//!
//! * `json.loads(bytes)`: encoding sniffing (UTF-8/16/32, BOM), the
//!   `NaN`/`Infinity` literals, lone surrogates, last-duplicate-wins, the
//!   4300-digit integer limit and the exact error texts;
//! * `int(value)` for the `exp`/`iat`/`nbf` claims (numeric strings, Unicode
//!   digits and underscores are accepted, floats are truncated);
//! * the non-validating base64 decoder used for JWK members;
//! * OpenSSL's verification rules (PSS accepts signatures shorter than the
//!   modulus, high-S ECDSA is accepted, EC coordinates are reduced mod p).
//!
//! Every rejection carries the text `str(exception)` had in Python, prefixed
//! with `Token validation failed: `. The behaviour is pinned by differential
//! fixtures recorded from the Python implementation (`testdata/oidc`).

use std::collections::VecDeque;
use std::sync::{Arc, Mutex as StdMutex, OnceLock};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use base64::Engine as _;
use base64::engine::general_purpose::URL_SAFE_NO_PAD;
use indexmap::IndexMap;
use rsa::BigUint;
use sha2::{Digest, Sha256, Sha384, Sha512};
use tokio::sync::Mutex;

use crate::domain::value_objects::TokenClaims;
use crate::shared::config::OidcConfig;
use crate::shared::error::{AppError, AppResult, ErrorKind};

use pyjson::{PyStr, Value};

/// Signature algorithms a token may use; anything else (HS*, `none`,
/// EdDSA, ES256K, ...) is refused before a key is touched.
const ALGORITHMS: [&str; 9] = [
    "RS256", "RS384", "RS512", "ES256", "ES384", "ES512", "PS256", "PS384", "PS512",
];
/// httpx timeout used for the discovery document (per socket operation).
const DISCOVERY_TIMEOUT: Duration = Duration::from_secs(10);
/// `PyJWKClient` default socket timeout for the JWKS fetch.
const JWKS_TIMEOUT: Duration = Duration::from_secs(30);
/// `PyJWKClient` default JWK-set cache lifespan, in seconds.
const JWKS_LIFESPAN: f64 = 300.0;
/// `PyJWKClient` default cooldown between forced refreshes on unknown `kid`.
const JWKS_COOLDOWN: f64 = 30.0;
/// `PyJWKClient(cache_keys=True)` LRU size (`max_cached_keys`).
const MAX_CACHED_KEYS: usize = 16;

type R<T> = Result<T, String>;

// ---------------------------------------------------------------------------
// Clock
// ---------------------------------------------------------------------------

/// Time source for claim checks and JWKS caching. Injectable so tests can pin
/// both clocks, the way the Python fixtures were recorded.
pub trait Clock: Send + Sync {
    /// Wall-clock Unix time in seconds (`datetime.now(utc).timestamp()`).
    fn now(&self) -> f64;
    /// Monotonic seconds (`time.monotonic()`), used for cache lifetimes.
    fn monotonic(&self) -> f64;
}

/// The real clocks.
#[derive(Debug, Default, Clone, Copy)]
pub struct SystemClock;

impl Clock for SystemClock {
    fn now(&self) -> f64 {
        let d = SystemTime::now().duration_since(UNIX_EPOCH).unwrap_or_default();
        // datetime has microsecond resolution.
        d.as_secs() as f64 + f64::from(d.subsec_micros()) / 1e6
    }

    fn monotonic(&self) -> f64 {
        static START: OnceLock<Instant> = OnceLock::new();
        START.get_or_init(Instant::now).elapsed().as_secs_f64()
    }
}

// ---------------------------------------------------------------------------
// Validator
// ---------------------------------------------------------------------------

/// Validates bearer JWTs via the issuer's discovery document and JWKS.
///
/// Discovery is resolved lazily on first validation so boot never depends on
/// the IdP being reachable; a failed discovery is retried on the next request
/// and a successful one is kept for the life of the process. The JWKS client
/// caches the key set for five minutes, refreshes it on an unknown `kid`
/// (subject to a 30 s cooldown) and keeps the last 16 resolved signing keys,
/// which also covers key rotation.
pub struct OidcTokenValidator {
    issuer: String,
    audiences: Vec<String>,
    leeway: i64,
    http: reqwest::Client,
    clock: Arc<dyn Clock>,
    jwks: Mutex<Option<Arc<JwksClient>>>,
}

impl std::fmt::Debug for OidcTokenValidator {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("OidcTokenValidator")
            .field("issuer", &self.issuer)
            .field("audiences", &self.audiences)
            .field("leeway", &self.leeway)
            .finish_non_exhaustive()
    }
}

/// Client settings shared by production and tests: no redirects, because
/// neither httpx (discovery) nor `PyJWKClient` (JWKS) followed them.
pub(crate) fn http_client_builder() -> reqwest::ClientBuilder {
    reqwest::Client::builder().redirect(reqwest::redirect::Policy::none())
}

fn shared_http() -> reqwest::Client {
    static CLIENT: OnceLock<reqwest::Client> = OnceLock::new();
    CLIENT
        .get_or_init(|| http_client_builder().build().unwrap_or_default())
        .clone()
}

impl OidcTokenValidator {
    pub fn new(issuer_url: &str, client_id: &str, audience: &str, leeway: i64) -> Self {
        Self::with_http_and_clock(
            issuer_url,
            client_id,
            audience,
            leeway,
            shared_http(),
            Arc::new(SystemClock),
        )
    }

    /// Like [`OidcTokenValidator::new`] with an explicit HTTP client and clock.
    pub fn with_http_and_clock(
        issuer_url: &str,
        client_id: &str,
        audience: &str,
        leeway: i64,
        http: reqwest::Client,
        clock: Arc<dyn Clock>,
    ) -> Self {
        let audiences = if audience.is_empty() {
            vec![client_id.to_string(), format!("api://{client_id}")]
        } else {
            vec![audience.to_string()]
        };
        Self {
            issuer: issuer_url.trim_end_matches('/').to_string(),
            audiences,
            leeway,
            http,
            clock,
            jwks: Mutex::new(None),
        }
    }

    /// Validates `token` and extracts its identity claims; every failure is a
    /// 401 `TokenValidation` error.
    pub async fn validate(&self, token: &str) -> AppResult<TokenClaims> {
        self.validate_inner(token)
            .await
            .map_err(|e| AppError::kind(ErrorKind::TokenValidation, format!("Token validation failed: {e}"), 401))
    }

    async fn jwks_client(&self) -> R<Arc<JwksClient>> {
        let mut slot = self.jwks.lock().await;
        if let Some(c) = slot.as_ref() {
            return Ok(c.clone());
        }
        let url = format!("{}/.well-known/openid-configuration", self.issuer);
        let body = fetch_discovery(&self.http, &url).await?;
        let doc = pyjson::loads(&body)?;
        let uri = jwks_uri_of(&doc)?;
        let client = Arc::new(JwksClient::new(uri, self.http.clone(), self.clock.clone())?);
        *slot = Some(client.clone());
        Ok(client)
    }

    async fn validate_inner(&self, token: &str) -> R<TokenClaims> {
        let jwks = self.jwks_client().await?;

        // PyJWKClient.get_signing_key_from_jwt: an unverified decode first, so
        // header and payload syntax errors surface before any key lookup.
        let jws = jws::load(token.as_bytes())?;
        let payload = jws::decode_payload(&jws.payload)?;
        let kid = match jws.header.get_str("kid") {
            Some(Value::Str(s)) => Some(s.clone()),
            _ => None,
        };
        let key = jwks.get_signing_key(kid).await?;

        // jwt.decode(token, key.key, algorithms=..., ...).
        let alg = match jws.header.get_str("alg") {
            None => return Err("Algorithm not specified".into()),
            Some(a) => a,
        };
        let alg = match alg {
            Value::Str(s) if !s.is_empty() => ALGORITHMS.iter().copied().find(|a| s.eq_str(a)),
            _ => None,
        }
        .ok_or("The specified alg value is not allowed")?;
        if !crypto::verify(alg, &key.material, &jws.signing_input, &jws.signature)? {
            return Err("Signature verification failed".into());
        }
        claims::validate(&payload, self.clock.now(), self.leeway, &self.issuer, &self.audiences)?;
        claims::extract(&payload)
    }
}

/// Builds the process validator; `None` disables authentication (blank
/// `oidc.issuer_url`, the dev default).
pub fn build_validator(cfg: &OidcConfig) -> Option<Arc<OidcTokenValidator>> {
    if cfg.issuer_url.is_empty() {
        return None;
    }
    Some(Arc::new(OidcTokenValidator::new(
        &cfg.issuer_url,
        &cfg.client_id,
        &cfg.audience,
        cfg.clock_skew_seconds,
    )))
}

// ---------------------------------------------------------------------------
// HTTP (discovery via httpx semantics, JWKS via urllib semantics)
// ---------------------------------------------------------------------------

enum FetchError {
    /// Failed before a response arrived (connect/DNS/timeouts).
    Transport { msg: String, timeout: bool },
    Status {
        code: u16,
        reason: String,
        url: String,
        location: Option<String>,
    },
}

fn transport_message(err: &reqwest::Error) -> (String, bool) {
    if err.is_timeout() {
        return ("timed out".into(), true);
    }
    let mut src: Option<&(dyn std::error::Error + 'static)> = Some(err);
    while let Some(e) = src {
        if let Some(io) = e.downcast_ref::<std::io::Error>() {
            if let Some(code) = io.raw_os_error() {
                let text = io.to_string();
                let text = text.split(" (os error").next().unwrap_or(&text).to_string();
                return (format!("[Errno {code}] {text}"), false);
            }
            let text = io.to_string();
            for (errno, phrase) in [
                (-2, "Name or service not known"),
                (-3, "Temporary failure in name resolution"),
                (-5, "No address associated with hostname"),
            ] {
                if text.contains(phrase) {
                    return (format!("[Errno {errno}] {phrase}"), false);
                }
            }
        }
        src = e.source();
    }
    (err.to_string(), false)
}

async fn http_get(http: &reqwest::Client, url: &str, timeout: Duration) -> Result<Vec<u8>, FetchError> {
    // Python's timeouts apply per socket operation, not to the whole exchange.
    let resp = match tokio::time::timeout(timeout, http.get(url).send()).await {
        Err(_) => {
            return Err(FetchError::Transport {
                msg: "timed out".into(),
                timeout: true,
            });
        }
        Ok(Err(e)) => {
            let (msg, timeout) = transport_message(&e);
            return Err(FetchError::Transport { msg, timeout });
        }
        Ok(Ok(r)) => r,
    };
    let status = resp.status();
    if !status.is_success() {
        return Err(FetchError::Status {
            code: status.as_u16(),
            reason: status.canonical_reason().unwrap_or("").to_string(),
            url: resp.url().to_string(),
            location: resp
                .headers()
                .get("location")
                .map(|v| String::from_utf8_lossy(v.as_bytes()).into_owned()),
        });
    }
    let mut resp = resp;
    let mut body = Vec::new();
    loop {
        match tokio::time::timeout(timeout, resp.chunk()).await {
            Err(_) => {
                return Err(FetchError::Transport {
                    msg: "timed out".into(),
                    timeout: true,
                });
            }
            Ok(Err(e)) => {
                let (msg, timeout) = transport_message(&e);
                return Err(FetchError::Transport { msg, timeout });
            }
            Ok(Ok(None)) => break,
            Ok(Ok(Some(c))) => body.extend_from_slice(&c),
        }
    }
    Ok(body)
}

/// `httpx.get(url, timeout=10)` + `raise_for_status()`, with httpx's texts.
async fn fetch_discovery(http: &reqwest::Client, url: &str) -> R<Vec<u8>> {
    match url_scheme_httpx(url) {
        None => return Err("Request URL is missing an 'http://' or 'https://' protocol.".into()),
        Some(s) if s != "http" && s != "https" => {
            return Err(format!("Request URL has an unsupported protocol '{s}://'."));
        }
        Some(_) => {}
    }
    if let Err(e) = reqwest::Url::parse(url) {
        return Err(format!("Invalid URL: {e}"));
    }
    http_get(http, url, DISCOVERY_TIMEOUT).await.map_err(|e| match e {
        FetchError::Transport { msg, .. } => msg,
        FetchError::Status {
            code,
            reason,
            url,
            location,
        } => {
            let kind = match code / 100 {
                1 => "Informational response",
                3 => "Redirect response",
                4 => "Client error",
                5 => "Server error",
                _ => "Invalid status code",
            };
            let help =
                format!("For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/{code}");
            match location {
                Some(loc) if matches!(code, 301 | 302 | 303 | 307 | 308) => {
                    format!("{kind} '{code} {reason}' for url '{url}'\nRedirect location: '{loc}'\n{help}")
                }
                _ => format!("{kind} '{code} {reason}' for url '{url}'\n{help}"),
            }
        }
    })
}

/// The scheme httpx's URL parser sees (lower-cased), if any.
fn url_scheme_httpx(url: &str) -> Option<String> {
    let colon = url.find(':')?;
    let scheme = &url[..colon];
    let mut chars = scheme.chars();
    let first = chars.next()?;
    if !first.is_ascii_alphabetic() || !chars.all(|c| c.is_ascii_alphanumeric() || "+-.".contains(c)) {
        return None;
    }
    Some(scheme.to_ascii_lowercase())
}

/// `response.json()["jwks_uri"]`, with Python's exception texts.
fn jwks_uri_of(doc: &Value) -> R<Value> {
    match doc {
        Value::Dict(d) => d
            .get(&PyStr::new("jwks_uri"))
            .cloned()
            .ok_or_else(|| "'jwks_uri'".to_string()),
        Value::List(_) => Err("list indices must be integers or slices, not str".into()),
        Value::Str(_) => Err("string indices must be integers, not 'str'".into()),
        other => Err(format!("'{}' object is not subscriptable", other.type_name())),
    }
}

// ---------------------------------------------------------------------------
// JWKS client (PyJWKClient(uri, cache_keys=True))
// ---------------------------------------------------------------------------

#[derive(Debug)]
struct Jwk {
    kid: Option<Value>,
    use_: Option<Value>,
    material: jwk::Material,
}

impl Jwk {
    fn is_signing_key(&self) -> bool {
        let use_ok = match &self.use_ {
            None | Some(Value::Null) => true,
            Some(Value::Str(s)) => s.eq_str("sig"),
            _ => false,
        };
        use_ok && self.kid.as_ref().is_some_and(Value::truthy)
    }

    fn matches(&self, kid: &Option<PyStr>) -> bool {
        match (&self.kid, kid) {
            (Some(Value::Str(a)), Some(b)) => a == b,
            (None | Some(Value::Null), None) => true,
            _ => false,
        }
    }
}

struct JwksState {
    /// Parsed key set and the monotonic time it was stored.
    cache: Option<(Arc<Vec<Arc<Jwk>>>, f64)>,
    last_successful_fetch: Option<f64>,
}

struct JwksClient {
    uri: String,
    http: reqwest::Client,
    clock: Arc<dyn Clock>,
    state: Mutex<JwksState>,
    /// `lru_cache(maxsize=16)` around `get_signing_key`: successful lookups
    /// only, no expiry, most recently used at the back.
    lru: StdMutex<VecDeque<(Option<PyStr>, Arc<Jwk>)>>,
}

impl JwksClient {
    fn new(uri: Value, http: reqwest::Client, clock: Arc<dyn Clock>) -> R<Self> {
        let uri = match uri {
            Value::Str(s) => s,
            // urlparse() on a non-str: falsy values parse as b'', the rest
            // have no .decode().
            v if !v.truthy() => {
                return Err("Invalid JWKS URI scheme b'': only 'http' and 'https' are supported.".into());
            }
            v => return Err(format!("'{}' object has no attribute 'decode'", v.type_name())),
        };
        let uri = uri.to_string_lossy();
        let scheme = urlsplit_scheme(&uri);
        if scheme != "http" && scheme != "https" {
            return Err(format!(
                "Invalid JWKS URI scheme {}: only 'http' and 'https' are supported.",
                crate::shared::pyfmt::repr_str(&scheme)
            ));
        }
        Ok(Self {
            uri,
            http,
            clock,
            state: Mutex::new(JwksState {
                cache: None,
                last_successful_fetch: None,
            }),
            lru: StdMutex::new(VecDeque::new()),
        })
    }

    async fn get_signing_key(&self, kid: Option<PyStr>) -> R<Arc<Jwk>> {
        {
            let mut lru = self.lru.lock().unwrap_or_else(|e| e.into_inner());
            if let Some(pos) = lru.iter().position(|(k, _)| *k == kid) {
                let entry = lru.remove(pos).expect("position is in range");
                let key = entry.1.clone();
                lru.push_back(entry);
                return Ok(key);
            }
        }
        let key = self.lookup(&kid).await?;
        let mut lru = self.lru.lock().unwrap_or_else(|e| e.into_inner());
        if !lru.iter().any(|(k, _)| *k == kid) {
            if lru.len() >= MAX_CACHED_KEYS {
                lru.pop_front();
            }
            lru.push_back((kid, key.clone()));
        }
        Ok(key)
    }

    /// `PyJWKClient.get_signing_key` (uncached body).
    async fn lookup(&self, kid: &Option<PyStr>) -> R<Arc<Jwk>> {
        let mut st = self.state.lock().await;
        let keys = self.signing_keys(&mut st, false).await?;
        if let Some(k) = keys.iter().find(|k| k.matches(kid)) {
            return Ok(k.clone());
        }
        let now = self.clock.monotonic();
        let cooling_down = st.last_successful_fetch.is_some_and(|t| now - t < JWKS_COOLDOWN);
        if !cooling_down {
            let keys = self.signing_keys(&mut st, true).await?;
            st.last_successful_fetch = Some(self.clock.monotonic());
            if let Some(k) = keys.iter().find(|k| k.matches(kid)) {
                return Ok(k.clone());
            }
        }
        let shown = kid.as_ref().map_or_else(|| "None".to_string(), PyStr::to_string_lossy);
        Err(format!("Unable to find a signing key that matches: \"{shown}\""))
    }

    async fn signing_keys(&self, st: &mut JwksState, refresh: bool) -> R<Vec<Arc<Jwk>>> {
        let set = self.jwk_set(st, refresh).await?;
        let keys: Vec<Arc<Jwk>> = set.iter().filter(|k| k.is_signing_key()).cloned().collect();
        if keys.is_empty() {
            return Err("The JWKS endpoint did not contain any signing keys".into());
        }
        Ok(keys)
    }

    async fn jwk_set(&self, st: &mut JwksState, refresh: bool) -> R<Arc<Vec<Arc<Jwk>>>> {
        if !refresh
            && let Some((set, ts)) = &st.cache
            && self.clock.monotonic() <= ts + JWKS_LIFESPAN
        {
            return Ok(set.clone());
        }
        // fetch_data(): the cache and the cooldown only move on success.
        let body = self.fetch().await?;
        let doc = pyjson::loads(&body)?;
        if !matches!(doc, Value::Dict(_)) {
            return Err("The JWKS endpoint did not return a JSON object".into());
        }
        let set = Arc::new(parse_jwk_set(&doc)?);
        let now = self.clock.monotonic();
        st.cache = Some((set.clone(), now));
        st.last_successful_fetch = Some(now);
        Ok(set)
    }

    async fn fetch(&self) -> R<Vec<u8>> {
        let wrap = |e: String| format!("Fail to fetch data from the url, err: \"{e}\"");
        if !urllib_has_host(&self.uri) {
            return Err(wrap("<urlopen error no host given>".into()));
        }
        if let Err(e) = reqwest::Url::parse(self.uri.trim()) {
            return Err(wrap(format!("<urlopen error {e}>")));
        }
        http_get(&self.http, self.uri.trim(), JWKS_TIMEOUT).await.map_err(|e| {
            wrap(match e {
                FetchError::Transport { msg, timeout: true } => msg,
                FetchError::Transport { msg, timeout: false } => format!("<urlopen error {msg}>"),
                FetchError::Status { code, reason, .. } => format!("HTTP Error {code}: {reason}"),
            })
        })
    }
}

/// `urllib.parse.urlsplit(uri).scheme`.
fn urlsplit_scheme(url: &str) -> String {
    let url = url.trim_start_matches(|c: char| c <= ' ');
    let url: String = url.chars().filter(|c| !matches!(c, '\t' | '\r' | '\n')).collect();
    if let Some(i) = url.find(':') {
        let head = &url[..i];
        let first = head.chars().next();
        if i > 0
            && first.is_some_and(|c| c.is_ascii_alphabetic())
            && head.chars().all(|c| c.is_ascii_alphanumeric() || "+-.".contains(c))
        {
            return head.to_ascii_lowercase();
        }
    }
    String::new()
}

/// `urllib.request.Request(uri).host` is non-empty (`scheme://host...`).
fn urllib_has_host(uri: &str) -> bool {
    let u = crate::shared::pyfmt::strip(uri);
    let Some(i) = u.find(':') else { return false };
    let rest = &u[i + 1..];
    let Some(rest) = rest.strip_prefix("//") else {
        return false;
    };
    let host_end = rest.find(['/', '#', '?']).unwrap_or(rest.len());
    host_end > 0
}

/// `PyJWKSet.from_dict(obj)`: unusable members are skipped, but a few
/// malformed JWKs raise non-PyJWT exceptions that abort the whole set.
fn parse_jwk_set(doc: &Value) -> R<Vec<Arc<Jwk>>> {
    let keys = doc.get_str("keys");
    let keys = match keys {
        None => return Err("The JWK Set did not contain any keys".into()),
        Some(v) if !v.truthy() => return Err("The JWK Set did not contain any keys".into()),
        Some(Value::List(items)) => items,
        Some(_) => return Err("Invalid JWK Set value".into()),
    };
    let mut out = Vec::new();
    for item in keys {
        let Value::Dict(_) = item else { continue };
        if let Some(material) = jwk::parse(item)? {
            out.push(Arc::new(Jwk {
                kid: item.get_str("kid").cloned(),
                use_: item.get_str("use").cloned(),
                material,
            }));
        }
    }
    if out.is_empty() {
        return Err("The JWK Set did not contain any usable keys. Perhaps 'cryptography' is not installed?".into());
    }
    Ok(out)
}

// ---------------------------------------------------------------------------
// JWS compact serialisation (PyJWS._load / _validate_headers)
// ---------------------------------------------------------------------------

mod jws {
    use super::*;

    pub(super) struct Jws {
        pub header: Value,
        pub payload: Vec<u8>,
        pub signing_input: Vec<u8>,
        pub signature: Vec<u8>,
    }

    const ALPHABET: &[u8] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";

    /// Strict base64url: canonical, unpadded, nothing outside the alphabet.
    pub(super) fn decode_segment(seg: &[u8], name: &str) -> R<Vec<u8>> {
        let err = || format!("Invalid {name} padding");
        if seg.len() % 4 == 1 || seg.iter().any(|c| !ALPHABET.contains(c)) {
            return Err(err());
        }
        let decoded = URL_SAFE_NO_PAD.decode(seg).map_err(|_| err())?;
        if URL_SAFE_NO_PAD.encode(&decoded).as_bytes() != seg {
            return Err(err());
        }
        Ok(decoded)
    }

    /// `_load` + `_validate_headers` + the RFC 7797 `b64` checks of
    /// `decode_complete` (no detached payload is ever supplied).
    pub(super) fn load(token: &[u8]) -> R<Jws> {
        let last = token.iter().rposition(|&c| c == b'.').ok_or("Not enough segments")?;
        let (signing_input, crypto) = (&token[..last], &token[last + 1..]);
        let first = signing_input
            .iter()
            .position(|&c| c == b'.')
            .ok_or("Not enough segments")?;
        let (header_seg, payload_seg) = (&signing_input[..first], &signing_input[first + 1..]);

        let header_data = decode_segment(header_seg, "header")?;
        let header = pyjson::loads(&header_data).map_err(|e| format!("Invalid header string: {e}"))?;
        if !matches!(header, Value::Dict(_)) {
            return Err("Invalid header string: must be a json object".into());
        }
        let b64_false = matches!(header.get_str("b64"), Some(Value::Bool(false)));
        let payload = if b64_false {
            if !payload_seg.is_empty() {
                return Err("Payload segment must be empty when 'b64' is false.".into());
            }
            Vec::new()
        } else {
            decode_segment(payload_seg, "payload")?
        };
        let signature = decode_segment(crypto, "crypto")?;

        if header.get_str("kid").is_some_and(|kid| !matches!(kid, Value::Str(_))) {
            return Err("Key ID header parameter must be a string".into());
        }
        if let Some(crit) = header.get_str("crit") {
            let items = match crit {
                Value::List(items) if !items.is_empty() => items,
                _ => return Err("Invalid 'crit' header: must be a non-empty list".into()),
            };
            for ext in items {
                let Value::Str(ext) = ext else {
                    return Err("Invalid 'crit' header: values must be strings".into());
                };
                if !ext.eq_str("b64") {
                    return Err(format!("Unsupported critical extension: {}", ext.to_string_lossy()));
                }
                if header.get_str("b64").is_none() {
                    return Err("Critical extension 'b64' is missing from headers".into());
                }
            }
        }
        if b64_false {
            let listed = match header.get_str("crit") {
                Some(Value::List(items)) => items.iter().any(|v| matches!(v, Value::Str(s) if s.eq_str("b64"))),
                _ => false,
            };
            if !listed {
                return Err("The 'b64' header parameter requires 'b64' to be listed in 'crit'.".into());
            }
            return Err("It is required that you pass in a value for the \"detached_payload\" argument to decode a message having the b64 header set to false.".into());
        }
        Ok(Jws {
            header,
            payload,
            signing_input: signing_input.to_vec(),
            signature,
        })
    }

    /// `PyJWT._decode_payload`.
    pub(super) fn decode_payload(payload: &[u8]) -> R<Value> {
        let v = pyjson::loads(payload).map_err(|e| format!("Invalid payload string: {e}"))?;
        if !matches!(v, Value::Dict(_)) {
            return Err("Invalid payload string: must be a json object".into());
        }
        Ok(v)
    }
}

// ---------------------------------------------------------------------------
// Registered-claim validation (PyJWT._validate_claims) and claim mapping
// ---------------------------------------------------------------------------

mod claims {
    use super::*;

    /// `iat > now + leeway` etc. compare a Python int with a float exactly;
    /// for a finite float `f`, `i > f` iff `i > floor(f)`.
    fn floor_i128(f: f64) -> i128 {
        f.floor() as i128
    }

    pub(super) fn validate(p: &Value, now: f64, leeway: i64, issuer: &str, audiences: &[String]) -> R<()> {
        for claim in ["exp", "iss", "sub"] {
            if matches!(p.get_str(claim), None | Some(Value::Null)) {
                return Err(format!("Token is missing the \"{claim}\" claim"));
            }
        }
        let leeway = leeway as f64;
        if let Some(v) = p.get_str("iat") {
            let iat = pyint::int(v).ok_or("Issued At claim (iat) must be an integer.")?;
            if iat > floor_i128(now + leeway) {
                return Err("The token is not yet valid (iat)".into());
            }
        }
        if let Some(v) = p.get_str("nbf") {
            let nbf = pyint::int(v).ok_or("Not Before claim (nbf) must be an integer.")?;
            if nbf > floor_i128(now + leeway) {
                return Err("The token is not yet valid (nbf)".into());
            }
        }
        if let Some(v) = p.get_str("exp") {
            let exp = pyint::int(v).ok_or("Expiration Time claim (exp) must be an integer.")?;
            if exp <= floor_i128(now - leeway) {
                return Err("Signature has expired".into());
            }
        }
        // Some IdPs (e.g. Auth0) emit `iss` with a trailing slash, so both
        // spellings of the configured issuer are accepted.
        match p.get_str("iss") {
            None => return Err("Token is missing the \"iss\" claim".into()),
            Some(Value::Str(iss)) => {
                if !iss.eq_str(issuer) && !iss.eq_str(&format!("{issuer}/")) {
                    return Err("Invalid issuer".into());
                }
            }
            Some(_) => return Err("Payload Issuer (iss) must be a string".into()),
        }
        let aud = match p.get_str("aud") {
            Some(v) if v.truthy() => v,
            _ => return Err("Token is missing the \"aud\" claim".into()),
        };
        let claimed: Vec<&PyStr> = match aud {
            Value::Str(s) => vec![s],
            Value::List(items) => {
                let mut out = Vec::with_capacity(items.len());
                for it in items {
                    let Value::Str(s) = it else {
                        return Err("Invalid claim format in token".into());
                    };
                    out.push(s);
                }
                out
            }
            _ => return Err("Invalid claim format in token".into()),
        };
        if !audiences.iter().any(|a| claimed.iter().any(|c| c.eq_str(a))) {
            return Err("Audience doesn't match".into());
        }
        if p.get_str("sub").is_some_and(|v| !matches!(v, Value::Str(_))) {
            return Err("Subject must be a string".into());
        }
        if p.get_str("jti").is_some_and(|v| !matches!(v, Value::Str(_))) {
            return Err("JWT ID must be a string".into());
        }
        Ok(())
    }

    /// Python stored whatever JSON value it found in `email`/`name`; only
    /// strings (or null) fit `TokenClaims`, anything else is rejected here.
    fn opt_string(claim: &str, v: Option<&Value>) -> R<Option<String>> {
        match v {
            None | Some(Value::Null) => Ok(None),
            Some(Value::Str(s)) => s
                .as_string()
                .map(Some)
                .ok_or_else(|| format!("{claim} claim is not valid Unicode")),
            Some(_) => Err(format!("{claim} claim must be a string")),
        }
    }

    pub(super) fn extract(p: &Value) -> R<TokenClaims> {
        let req = |claim: &str| match p.get_str(claim) {
            Some(Value::Str(s)) => s
                .as_string()
                .ok_or_else(|| format!("{claim} claim is not valid Unicode")),
            _ => Err(format!("{claim} claim must be a string")),
        };
        let issuer = req("iss")?;
        let subject = req("sub")?;
        let email_raw = p.get_str("email");
        // `email or preferred_username`
        let email_value = match email_raw {
            Some(v) if v.truthy() => Some(v),
            _ => p.get_str("preferred_username"),
        };
        let email = opt_string("email", email_value)?;
        let name = opt_string("name", p.get_str("name"))?;
        let email_present = !matches!(email_raw, None | Some(Value::Null));
        let email_verified = email_present && matches!(p.get_str("email_verified"), Some(Value::Bool(true)));
        Ok(TokenClaims {
            issuer,
            subject,
            email,
            name,
            email_verified,
        })
    }
}

// ---------------------------------------------------------------------------
// JWK parsing (PyJWK + Algorithm.from_jwk + cryptography key validation)
// ---------------------------------------------------------------------------

mod jwk {
    use super::*;

    #[derive(Debug, Clone, Copy, PartialEq, Eq)]
    pub(super) enum Curve {
        P256,
        P384,
        P521,
        K256,
    }

    impl Curve {
        pub(super) fn openssl_name(self) -> &'static str {
            match self {
                Curve::P256 => "secp256r1",
                Curve::P384 => "secp384r1",
                Curve::P521 => "secp521r1",
                Curve::K256 => "secp256k1",
            }
        }

        fn size(self) -> usize {
            match self {
                Curve::P256 | Curve::K256 => 32,
                Curve::P384 => 48,
                Curve::P521 => 66,
            }
        }
    }

    /// The key object `PyJWK.key` would hold.
    #[derive(Debug)]
    pub(super) enum Material {
        Rsa {
            n: BigUint,
            e: BigUint,
        },
        /// A private RSA JWK: PyJWT hands the private key to `verify`, which
        /// it does not have.
        RsaPrivate,
        /// Public point, coordinates already reduced mod p (uncompressed SEC1).
        Ec {
            curve: Curve,
            sec1: Vec<u8>,
        },
        Okp,
        Oct,
    }

    enum Family {
        None,
        Hmac,
        Rsa,
        Ec,
        Okp,
    }

    fn get<'a>(obj: &'a Value, k: &str) -> Option<&'a Value> {
        obj.get_str(k)
    }

    fn str_is(v: Option<&Value>, s: &str) -> bool {
        matches!(v, Some(Value::Str(x)) if x.eq_str(s))
    }

    /// `base64url_decode(value)`: non-str raises TypeError (key skipped).
    fn b64(v: Option<&Value>) -> Option<Vec<u8>> {
        match v {
            Some(Value::Str(s)) => b64lenient::base64url_decode(&s.to_utf8()?),
            _ => None,
        }
    }

    fn b64_uint(v: Option<&Value>) -> Option<BigUint> {
        b64(v).map(|b| BigUint::from_bytes_be(&b))
    }

    /// `Ok(None)`: the JWK is skipped; `Err`: the whole JWK set fails.
    pub(super) fn parse(obj: &Value) -> R<Option<Material>> {
        let kty = get(obj, "kty");
        if !kty.is_some_and(Value::truthy) {
            return Ok(None);
        }
        let mut alg = get(obj, "alg").cloned().filter(Value::truthy);
        if alg.is_none() {
            let crv = get(obj, "crv");
            let name = if str_is(kty, "EC") {
                if str_is(crv, "P-256") || !crv.is_some_and(Value::truthy) {
                    "ES256"
                } else if str_is(crv, "P-384") {
                    "ES384"
                } else if str_is(crv, "P-521") {
                    "ES512"
                } else if str_is(crv, "secp256k1") {
                    "ES256K"
                } else {
                    return Ok(None);
                }
            } else if str_is(kty, "RSA") {
                "RS256"
            } else if str_is(kty, "oct") {
                "HS256"
            } else if str_is(kty, "OKP") {
                if !crv.is_some_and(Value::truthy) || !str_is(crv, "Ed25519") {
                    return Ok(None);
                }
                "EdDSA"
            } else {
                return Ok(None);
            };
            alg = Some(Value::Str(PyStr::new(name)));
        }
        let family = match alg.as_ref().expect("set above") {
            v @ (Value::List(_) | Value::Dict(_)) => {
                let t = v.type_name();
                return Err(format!("cannot use '{t}' as a dict key (unhashable type: '{t}')"));
            }
            Value::Str(s) => match s.to_string_lossy().as_str() {
                "none" => Family::None,
                "HS256" | "HS384" | "HS512" => Family::Hmac,
                "RS256" | "RS384" | "RS512" | "PS256" | "PS384" | "PS512" => Family::Rsa,
                "ES256" | "ES256K" | "ES384" | "ES521" | "ES512" => Family::Ec,
                "EdDSA" => Family::Okp,
                _ => return Ok(None),
            },
            _ => return Ok(None),
        };
        match family {
            // NoneAlgorithm.from_jwk raises NotImplementedError() (empty text).
            Family::None => Err(String::new()),
            Family::Hmac => {
                if !str_is(get(obj, "kty"), "oct") {
                    return Ok(None);
                }
                let Some(k) = get(obj, "k") else {
                    return Err("'k'".into());
                };
                Ok(b64(Some(k)).filter(|b| !b.is_empty()).map(|_| Material::Oct))
            }
            Family::Rsa => Ok(parse_rsa(obj)),
            Family::Ec => Ok(parse_ec(obj)),
            Family::Okp => Ok(parse_okp(obj)),
        }
    }

    fn parse_rsa(obj: &Value) -> Option<Material> {
        if !str_is(get(obj, "kty"), "RSA") {
            return None;
        }
        let has = |k: &str| get(obj, k).is_some();
        if has("d") && has("e") && has("n") {
            if has("oth") {
                return None;
            }
            let props = ["p", "q", "dp", "dq", "qi"];
            let found = props.iter().filter(|k| has(k)).count();
            if found != 0 && found != props.len() {
                return None;
            }
            let e = b64_uint(get(obj, "e"))?;
            let n = b64_uint(get(obj, "n"))?;
            let d = b64_uint(get(obj, "d"))?;
            let valid = if found != 0 {
                let p = b64_uint(get(obj, "p"))?;
                let q = b64_uint(get(obj, "q"))?;
                let dp = b64_uint(get(obj, "dp"))?;
                let dq = b64_uint(get(obj, "dq"))?;
                let qi = b64_uint(get(obj, "qi"))?;
                let memo_key = [&n, &e, &d, &p, &q, &dp, &dq, &qi].map(BigUint::to_bytes_be).concat();
                bigmath::memo(memo_key, || {
                    bigmath::rsa_private_valid(&n, &e, &d, &p, &q, &dp, &dq, &qi)
                })
            } else {
                let memo_key = [&n, &e, &d].map(BigUint::to_bytes_be).concat();
                bigmath::memo(memo_key, || bigmath::rsa_recover_valid(&n, &e, &d))
            };
            return valid.then_some(Material::RsaPrivate);
        }
        if has("n") && has("e") {
            let e = b64_uint(get(obj, "e"))?;
            let n = b64_uint(get(obj, "n"))?;
            // RSAPublicNumbers.public_key()
            let three = BigUint::from(3u8);
            if n < three || e < three || e >= n || !bigmath::is_odd(&e) {
                return None;
            }
            return Some(Material::Rsa { n, e });
        }
        None
    }

    fn parse_ec(obj: &Value) -> Option<Material> {
        if !str_is(get(obj, "kty"), "EC") {
            return None;
        }
        if get(obj, "x").is_none() || get(obj, "y").is_none() {
            return None;
        }
        let x = b64(get(obj, "x"))?;
        let y = b64(get(obj, "y"))?;
        let crv = get(obj, "crv");
        let curve = if str_is(crv, "P-256") {
            Curve::P256
        } else if str_is(crv, "P-384") {
            Curve::P384
        } else if str_is(crv, "P-521") {
            Curve::P521
        } else if str_is(crv, "secp256k1") {
            Curve::K256
        } else {
            return None;
        };
        if x.len() != curve.size() || y.len() != curve.size() {
            return None;
        }
        let sec1 = bigmath::ec_public_point(curve, &x, &y)?;
        if get(obj, "d").is_some() {
            let d = b64(get(obj, "d"))?;
            if d.len() != x.len() || !bigmath::ec_private_matches(curve, &d, &sec1) {
                return None;
            }
        }
        Some(Material::Ec { curve, sec1 })
    }

    fn parse_okp(obj: &Value) -> Option<Material> {
        if !str_is(get(obj, "kty"), "OKP") {
            return None;
        }
        let crv = get(obj, "crv");
        let len = if str_is(crv, "Ed25519") {
            32
        } else if str_is(crv, "Ed448") {
            57
        } else {
            return None;
        };
        get(obj, "x")?;
        let x = b64(get(obj, "x"))?;
        if get(obj, "d").is_some() {
            // The derived public key cannot be checked against `x` without an
            // Ed25519/Ed448 implementation; lengths are what is checked.
            let d = b64(get(obj, "d"))?;
            return (d.len() == len && x.len() == len).then_some(Material::Okp);
        }
        (x.len() == len).then_some(Material::Okp)
    }
}

// ---------------------------------------------------------------------------
// Big-number helpers: key validation the way cryptography/OpenSSL does it
// ---------------------------------------------------------------------------

mod bigmath {
    use super::*;

    fn zero() -> BigUint {
        BigUint::from(0u8)
    }

    fn one() -> BigUint {
        BigUint::from(1u8)
    }

    /// Remembers the verdict of the expensive private-key checks: the same
    /// JWK set is re-parsed on every refresh, and recovering factors for an
    /// inconsistent `d` walks hundreds of bases.
    pub(super) fn memo(key: Vec<u8>, f: impl FnOnce() -> bool) -> bool {
        static MEMO: OnceLock<StdMutex<std::collections::HashMap<Vec<u8>, bool>>> = OnceLock::new();
        let memo = MEMO.get_or_init(Default::default);
        if let Some(&v) = memo.lock().unwrap_or_else(|e| e.into_inner()).get(&key) {
            return v;
        }
        let v = f();
        let mut m = memo.lock().unwrap_or_else(|e| e.into_inner());
        if m.len() >= 256 {
            m.clear();
        }
        m.insert(key, v);
        v
    }

    pub(super) fn is_odd(x: &BigUint) -> bool {
        x.to_bytes_be().last().is_some_and(|b| b & 1 == 1)
    }

    fn gcd(a: &BigUint, b: &BigUint) -> BigUint {
        let (mut a, mut b) = (a.clone(), b.clone());
        while b != zero() {
            let r = &a % &b;
            a = b;
            b = r;
        }
        a
    }

    fn probably_prime(n: &BigUint) -> bool {
        let small = [
            2u32, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47, 53, 59, 61, 67, 71,
        ];
        if *n < BigUint::from(2u8) {
            return false;
        }
        for p in small {
            let p = BigUint::from(p);
            if *n == p {
                return true;
            }
            if n % &p == zero() {
                return false;
            }
        }
        let n1 = n - one();
        let mut d = n1.clone();
        let mut s = 0u32;
        while !is_odd(&d) {
            d >>= 1usize;
            s += 1;
        }
        'bases: for a in small {
            let mut x = BigUint::from(a).modpow(&d, n);
            if x == one() || x == n1 {
                continue;
            }
            for _ in 1..s {
                x = (&x * &x) % n;
                if x == n1 {
                    continue 'bases;
                }
            }
            return false;
        }
        true
    }

    /// `RSAPrivateNumbers.private_key()`: cryptography's component checks
    /// followed by OpenSSL's `RSA_check_key`.
    #[allow(clippy::too_many_arguments)]
    pub(super) fn rsa_private_valid(
        n: &BigUint,
        e: &BigUint,
        d: &BigUint,
        p: &BigUint,
        q: &BigUint,
        dp: &BigUint,
        dq: &BigUint,
        qi: &BigUint,
    ) -> bool {
        let three = BigUint::from(3u8);
        if *n < three || p >= n || q >= n || dp >= n || dq >= n || qi >= n || d >= n {
            return false;
        }
        if *e < three || e >= n || !is_odd(e) || !is_odd(dp) || !is_odd(dq) || p * q != *n {
            return false;
        }
        if *p < BigUint::from(2u8) || *q < BigUint::from(2u8) {
            return false;
        }
        let (p1, q1) = (p - one(), q - one());
        let lcm = (&p1 * &q1) / gcd(&p1, &q1);
        if (d * e) % &lcm != one() || *dp != d % &p1 || *dq != d % &q1 || (qi * q) % p != one() {
            return false;
        }
        probably_prime(p) && probably_prime(q)
    }

    /// `rsa_recover_prime_factors(n, e, d)` followed by the CRT derivation and
    /// `private_key()`; recovered factors are consistent by construction.
    pub(super) fn rsa_recover_valid(n: &BigUint, e: &BigUint, d: &BigUint) -> bool {
        let three = BigUint::from(3u8);
        if *n < three || *e < three || e >= n || !is_odd(e) || d >= n {
            return false;
        }
        let de = d * e;
        if de < BigUint::from(2u8) {
            return false;
        }
        let ktot = de - one();
        let mut t = ktot.clone();
        while t != zero() && !is_odd(&t) {
            t >>= 1usize;
        }
        let n1 = n - one();
        let mut a = BigUint::from(2u8);
        let limit = BigUint::from(1000u32);
        while a < limit {
            let mut k = t.clone();
            while k < ktot {
                let cand = a.modpow(&k, n);
                if cand != one() && cand != n1 && (&cand * &cand) % n == one() {
                    let p = gcd(&(&cand + one()), n);
                    if p == one() || p == *n || n % &p != zero() {
                        return false;
                    }
                    let q = n / &p;
                    let (p, q) = if p > q { (p, q) } else { (q, p) };
                    let (p1, q1) = (&p - one(), &q - one());
                    let dp = d % &p1;
                    let dq = d % &q1;
                    let qi = q.modpow(&(&p - BigUint::from(2u8)), &p);
                    return rsa_private_valid(n, e, d, &p, &q, &dp, &dq, &qi);
                }
                k = &k * BigUint::from(2u8);
            }
            a = &a + BigUint::from(2u8);
        }
        false
    }

    fn field_prime(curve: jwk::Curve) -> BigUint {
        let hex: &str = match curve {
            jwk::Curve::P256 => "ffffffff00000001000000000000000000000000ffffffffffffffffffffffff",
            jwk::Curve::P384 => {
                "fffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffeffffffff0000000000000000ffffffff"
            }
            jwk::Curve::P521 => {
                "01ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
            }
            jwk::Curve::K256 => "fffffffffffffffffffffffffffffffffffffffffffffffffffffffefffffc2f",
        };
        BigUint::from_bytes_be(&hex::decode(hex).expect("valid constant"))
    }

    fn to_fixed(x: &BigUint, len: usize) -> Vec<u8> {
        let b = x.to_bytes_be();
        let mut out = vec![0u8; len.saturating_sub(b.len())];
        out.extend_from_slice(&b[b.len().saturating_sub(len)..]);
        out
    }

    /// `EllipticCurvePublicNumbers(x, y, curve).public_key()`: OpenSSL reduces
    /// the coordinates mod p, then requires a point on the curve.
    pub(super) fn ec_public_point(curve: jwk::Curve, x: &[u8], y: &[u8]) -> Option<Vec<u8>> {
        let p = field_prime(curve);
        let size = match curve {
            jwk::Curve::P256 | jwk::Curve::K256 => 32,
            jwk::Curve::P384 => 48,
            jwk::Curve::P521 => 66,
        };
        let xr = BigUint::from_bytes_be(x) % &p;
        let yr = BigUint::from_bytes_be(y) % &p;
        let mut sec1 = vec![4u8];
        sec1.extend(to_fixed(&xr, size));
        sec1.extend(to_fixed(&yr, size));
        let ok = match curve {
            jwk::Curve::P256 => p256::ecdsa::VerifyingKey::from_sec1_bytes(&sec1).is_ok(),
            jwk::Curve::P384 => p384::ecdsa::VerifyingKey::from_sec1_bytes(&sec1).is_ok(),
            jwk::Curve::P521 => p521::ecdsa::VerifyingKey::from_sec1_bytes(&sec1).is_ok(),
            jwk::Curve::K256 => {
                // y^2 = x^3 + 7
                let lhs = (&yr * &yr) % &p;
                let rhs = ((&xr * &xr % &p) * &xr + BigUint::from(7u8)) % &p;
                lhs == rhs
            }
        };
        ok.then_some(sec1)
    }

    /// `EllipticCurvePrivateNumbers(d, public).private_key()`: d in [1, n-1]
    /// and d·G equal to the published point.
    pub(super) fn ec_private_matches(curve: jwk::Curve, d: &[u8], sec1: &[u8]) -> bool {
        use p256::elliptic_curve::sec1::ToEncodedPoint;
        match curve {
            jwk::Curve::P256 => {
                p256::SecretKey::from_slice(d).is_ok_and(|k| k.public_key().to_encoded_point(false).as_bytes() == sec1)
            }
            jwk::Curve::P384 => {
                p384::SecretKey::from_slice(d).is_ok_and(|k| k.public_key().to_encoded_point(false).as_bytes() == sec1)
            }
            jwk::Curve::P521 => {
                p521::SecretKey::from_slice(d).is_ok_and(|k| k.public_key().to_encoded_point(false).as_bytes() == sec1)
            }
            jwk::Curve::K256 => memo([d, sec1].concat(), || k256_mul_base(d).is_some_and(|pt| pt == sec1)),
        }
    }

    /// d·G on secp256k1 (affine double-and-add; only used to validate rare
    /// private JWKs, so speed is irrelevant).
    fn k256_mul_base(d: &[u8]) -> Option<Vec<u8>> {
        let p = field_prime(jwk::Curve::K256);
        let n = BigUint::from_bytes_be(
            &hex::decode("fffffffffffffffffffffffffffffffebaaedce6af48a03bbfd25e8cd0364141").expect("const"),
        );
        let k = BigUint::from_bytes_be(d);
        if k == zero() || k >= n {
            return None;
        }
        let gx = BigUint::from_bytes_be(
            &hex::decode("79be667ef9dcbbac55a06295ce870b07029bfcdb2dce28d959f2815b16f81798").expect("const"),
        );
        let gy = BigUint::from_bytes_be(
            &hex::decode("483ada7726a3c4655da4fbfc0e1108a8fd17b448a68554199c47d08ffb10d4b8").expect("const"),
        );
        let inv = |a: &BigUint| a.modpow(&(&p - BigUint::from(2u8)), &p);
        let sub = |a: &BigUint, b: &BigUint| ((a + &p) - (b % &p)) % &p;
        type Pt = Option<(BigUint, BigUint)>;
        let add = |a: &Pt, b: &Pt| -> Pt {
            match (a, b) {
                (None, x) | (x, None) => x.clone(),
                (Some((x1, y1)), Some((x2, y2))) => {
                    let lambda = if x1 == x2 {
                        if (y1 + y2) % &p == zero() {
                            return None;
                        }
                        (BigUint::from(3u8) * x1 * x1 % &p) * inv(&(BigUint::from(2u8) * y1 % &p)) % &p
                    } else {
                        sub(y2, y1) * inv(&sub(x2, x1)) % &p
                    };
                    let x3 = sub(&sub(&(&lambda * &lambda % &p), x1), x2);
                    let y3 = sub(&(&lambda * &sub(x1, &x3) % &p), y1);
                    Some((x3, y3))
                }
            }
        };
        let mut acc: Pt = None;
        let base: Pt = Some((gx, gy));
        for byte in k.to_bytes_be() {
            for bit in (0..8).rev() {
                acc = add(&acc, &acc);
                if byte >> bit & 1 == 1 {
                    acc = add(&acc, &base);
                }
            }
        }
        let (x, y) = acc?;
        let mut out = vec![4u8];
        out.extend(to_fixed(&x, 32));
        out.extend(to_fixed(&y, 32));
        Some(out)
    }
}

// ---------------------------------------------------------------------------
// Signature verification (PyJWT algorithms on top of OpenSSL semantics)
// ---------------------------------------------------------------------------

mod crypto {
    use super::jwk::{Curve, Material};
    use super::*;

    fn digest(bits: &str, data: &[u8]) -> Vec<u8> {
        match bits {
            "256" => Sha256::digest(data).to_vec(),
            "384" => Sha384::digest(data).to_vec(),
            _ => Sha512::digest(data).to_vec(),
        }
    }

    /// `Ok(false)` is a bad signature; `Err` is an exception PyJWT would have
    /// raised while preparing the key.
    pub(super) fn verify(alg: &str, key: &Material, msg: &[u8], sig: &[u8]) -> R<bool> {
        let bits = &alg[2..];
        if alg.starts_with("ES") {
            let expected = match bits {
                "256" => Curve::P256,
                "384" => Curve::P384,
                _ => Curve::P521,
            };
            return match key {
                Material::Ec { curve, sec1 } => {
                    if *curve != expected {
                        return Err(format!(
                            "The key's curve '{}' does not match the expected curve '{}' for this algorithm",
                            curve.openssl_name(),
                            expected.openssl_name()
                        ));
                    }
                    Ok(verify_ecdsa(expected, sec1, &digest(bits, msg), sig))
                }
                // ECAlgorithm.prepare_key(bytes): load_pem_private_key fails.
                Material::Oct => Err("Unable to load PEM file. See https://cryptography.io/en/latest/faq/#why-can-t-i-import-my-pem-file for more details. MalformedFraming".into()),
                _ => Err("Expecting a PEM-formatted key.".into()),
            };
        }
        match key {
            Material::Rsa { n, e } => {
                let hash = digest(bits, msg);
                Ok(if alg.starts_with("PS") {
                    verify_pss(n, e, &hash, bits, sig)
                } else {
                    verify_pkcs1(n, e, &hash, bits, sig)
                })
            }
            Material::RsaPrivate => Err(
                "'cryptography.hazmat.bindings._rust.openssl.rsa.RSAPrivateKey' object has no attribute 'verify'"
                    .into(),
            ),
            Material::Oct => Err("Could not parse the provided public key.".into()),
            _ => Err("Expecting a PEM-formatted key.".into()),
        }
    }

    fn verify_ecdsa(curve: Curve, sec1: &[u8], hash: &[u8], sig: &[u8]) -> bool {
        use p256::ecdsa::signature::hazmat::PrehashVerifier;
        // Raw r||s of exactly twice the field size; r, s in [1, n-1]; high-S
        // is accepted (OpenSSL does not normalise).
        match curve {
            Curve::P256 => {
                let (Ok(k), Ok(s)) = (
                    p256::ecdsa::VerifyingKey::from_sec1_bytes(sec1),
                    p256::ecdsa::Signature::from_slice(sig),
                ) else {
                    return false;
                };
                k.verify_prehash(hash, &s).is_ok()
            }
            Curve::P384 => {
                let (Ok(k), Ok(s)) = (
                    p384::ecdsa::VerifyingKey::from_sec1_bytes(sec1),
                    p384::ecdsa::Signature::from_slice(sig),
                ) else {
                    return false;
                };
                k.verify_prehash(hash, &s).is_ok()
            }
            Curve::P521 => {
                let (Ok(k), Ok(s)) = (
                    p521::ecdsa::VerifyingKey::from_sec1_bytes(sec1),
                    p521::ecdsa::Signature::from_slice(sig),
                ) else {
                    return false;
                };
                k.verify_prehash(hash, &s).is_ok()
            }
            Curve::K256 => false,
        }
    }

    /// OpenSSL `rsa_ossl_public_decrypt`: modulus/exponent limits, then
    /// `sig^e mod n` as a k-byte block. `None` when OpenSSL errors out.
    fn rsa_public_op(n: &BigUint, e: &BigUint, sig: &[u8]) -> Option<Vec<u8>> {
        let k = n.bits().div_ceil(8);
        if n.bits() > 16384 || e >= n || (n.bits() > 3072 && e.bits() > 64) || sig.len() > k {
            return None;
        }
        // Montgomery multiplication needs an odd modulus.
        if !bigmath::is_odd(n) {
            return None;
        }
        let s = BigUint::from_bytes_be(sig);
        if s >= *n {
            return None;
        }
        let m = s.modpow(e, n).to_bytes_be();
        let mut em = vec![0u8; k - m.len()];
        em.extend_from_slice(&m);
        Some(em)
    }

    fn digest_info_prefix(bits: &str) -> &'static [u8] {
        match bits {
            "256" => &[
                0x30, 0x31, 0x30, 0x0d, 0x06, 0x09, 0x60, 0x86, 0x48, 0x01, 0x65, 0x03, 0x04, 0x02, 0x01, 0x05, 0x00,
                0x04, 0x20,
            ],
            "384" => &[
                0x30, 0x41, 0x30, 0x0d, 0x06, 0x09, 0x60, 0x86, 0x48, 0x01, 0x65, 0x03, 0x04, 0x02, 0x02, 0x05, 0x00,
                0x04, 0x30,
            ],
            _ => &[
                0x30, 0x51, 0x30, 0x0d, 0x06, 0x09, 0x60, 0x86, 0x48, 0x01, 0x65, 0x03, 0x04, 0x02, 0x03, 0x05, 0x00,
                0x04, 0x40,
            ],
        }
    }

    /// RSASSA-PKCS1-v1_5: the signature must be exactly k bytes and decode to
    /// the one valid encoding.
    fn verify_pkcs1(n: &BigUint, e: &BigUint, hash: &[u8], bits: &str, sig: &[u8]) -> bool {
        let k = n.bits().div_ceil(8);
        if sig.len() != k {
            return false;
        }
        let Some(em) = rsa_public_op(n, e, sig) else {
            return false;
        };
        let prefix = digest_info_prefix(bits);
        let t_len = prefix.len() + hash.len();
        if k < t_len + 11 {
            return false;
        }
        let mut expected = vec![0x00, 0x01];
        expected.resize(k - t_len - 1, 0xff);
        expected.push(0x00);
        expected.extend_from_slice(prefix);
        expected.extend_from_slice(hash);
        em == expected
    }

    fn mgf1(seed: &[u8], len: usize, bits: &str) -> Vec<u8> {
        let mut out = Vec::with_capacity(len + 64);
        let mut counter = 0u32;
        while out.len() < len {
            let mut data = seed.to_vec();
            data.extend_from_slice(&counter.to_be_bytes());
            out.extend(digest(bits, &data));
            counter += 1;
        }
        out.truncate(len);
        out
    }

    /// RSASSA-PSS with MGF1 and salt length = digest length, following
    /// OpenSSL's `RSA_verify_PKCS1_PSS_mgf1` (shorter signatures are
    /// zero-extended, as OpenSSL does).
    fn verify_pss(n: &BigUint, e: &BigUint, hash: &[u8], bits: &str, sig: &[u8]) -> bool {
        let Some(em_full) = rsa_public_op(n, e, sig) else {
            return false;
        };
        let h_len = hash.len();
        let s_len = h_len;
        let ms_bits = (n.bits() - 1) & 7;
        if ms_bits == 0 {
            if em_full[0] != 0 {
                return false;
            }
        } else if em_full[0] & (0xffu8 << ms_bits) != 0 {
            return false;
        }
        let em: &[u8] = if ms_bits == 0 { &em_full[1..] } else { &em_full };
        let em_len = em.len();
        if em_len < h_len + 2 || em_len < h_len + s_len + 2 || em[em_len - 1] != 0xbc {
            return false;
        }
        let masked_len = em_len - h_len - 1;
        let h = &em[masked_len..masked_len + h_len];
        let mut db = mgf1(h, masked_len, bits);
        for (d, m) in db.iter_mut().zip(&em[..masked_len]) {
            *d ^= m;
        }
        if ms_bits != 0 {
            db[0] &= 0xff >> (8 - ms_bits);
        }
        let mut i = 0;
        while i < masked_len - 1 && db[i] == 0 {
            i += 1;
        }
        if db[i] != 0x01 {
            return false;
        }
        i += 1;
        if masked_len - i != s_len {
            return false;
        }
        let mut m_prime = vec![0u8; 8];
        m_prime.extend_from_slice(hash);
        m_prime.extend_from_slice(&db[i..]);
        digest(bits, &m_prime) == h
    }
}

// ---------------------------------------------------------------------------
// int(value) for the numeric date claims
// ---------------------------------------------------------------------------

mod pyint {
    use super::*;

    /// Integers are compared against `now ± leeway` (well inside ±1e20);
    /// clamping keeps the comparison exact.
    pub(super) const CLAMP: i128 = 1_000_000_000_000_000_000_000_000_000_000_000_000;

    /// Unicode decimal-digit runs (Nd, Unicode 16.0 as in Python 3.14): the
    /// code point of each run's zero.
    const DECIMAL_ZEROS: [u32; 75] = [
        0x660, 0x6F0, 0x7C0, 0x966, 0x9E6, 0xA66, 0xAE6, 0xB66, 0xBE6, 0xC66, 0xCE6, 0xD66, 0xDE6, 0xE50, 0xED0, 0xF20,
        0x1040, 0x1090, 0x17E0, 0x1810, 0x1946, 0x19D0, 0x1A80, 0x1A90, 0x1B50, 0x1BB0, 0x1C40, 0x1C50, 0xA620, 0xA8D0,
        0xA900, 0xA9D0, 0xA9F0, 0xAA50, 0xABF0, 0xFF10, 0x104A0, 0x10D30, 0x10D40, 0x11066, 0x110F0, 0x11136, 0x111D0,
        0x112F0, 0x11450, 0x114D0, 0x11650, 0x116C0, 0x116D0, 0x116DA, 0x11730, 0x118E0, 0x11950, 0x11BF0, 0x11C50,
        0x11D50, 0x11DA0, 0x11F50, 0x16130, 0x16A60, 0x16AC0, 0x16B50, 0x16D70, 0x1CCF0, 0x1D7CE, 0x1D7D8, 0x1D7E2,
        0x1D7EC, 0x1D7F6, 0x1E140, 0x1E2F0, 0x1E4F0, 0x1E5F1, 0x1E950, 0x1FBF0,
    ];

    fn decimal(cp: u32) -> Option<u8> {
        DECIMAL_ZEROS
            .iter()
            .find(|&&z| (z..z + 10).contains(&cp))
            .map(|z| (cp - z) as u8)
    }

    /// `str.isspace()` for code points >= 127.
    fn py_space(cp: u32) -> bool {
        matches!(
            cp,
            0x85 | 0xA0 | 0x1680 | 0x2000..=0x200A | 0x2028 | 0x2029 | 0x202F | 0x205F | 0x3000
        )
    }

    /// `int(v)`; `None` where Python raises ValueError/TypeError/OverflowError.
    pub(super) fn int(v: &Value) -> Option<i128> {
        match v {
            Value::Bool(b) => Some(i128::from(*b)),
            Value::Int(i) => Some(*i),
            Value::Float(f) if f.is_finite() => {
                let t = f.trunc();
                Some(if t.abs() >= 1e36 {
                    if t > 0.0 { CLAMP } else { -CLAMP }
                } else {
                    t as i128
                })
            }
            Value::Str(s) => int_str(s.code_points()),
            _ => None,
        }
    }

    /// `int(str)`: `_PyUnicode_TransformDecimalAndSpaceToASCII` followed by
    /// `PyLong_FromString(base=10)`.
    fn int_str(cps: &[u32]) -> Option<i128> {
        let mut ascii = Vec::with_capacity(cps.len());
        for &cp in cps {
            if cp < 127 {
                ascii.push(cp as u8);
            } else if py_space(cp) {
                ascii.push(b' ');
            } else {
                ascii.push(b'0' + decimal(cp)?);
            }
        }
        let is_space = |c: u8| matches!(c, b' ' | b'\t' | b'\n' | 0x0b | 0x0c | b'\r');
        let mut i = 0;
        while i < ascii.len() && is_space(ascii[i]) {
            i += 1;
        }
        let neg = match ascii.get(i) {
            Some(b'-') => {
                i += 1;
                true
            }
            Some(b'+') => {
                i += 1;
                false
            }
            _ => false,
        };
        let mut value: i128 = 0;
        let mut digits = 0usize;
        let mut prev_underscore = false;
        while i < ascii.len() {
            let c = ascii[i];
            if c.is_ascii_digit() {
                digits += 1;
                value = (value * 10 + i128::from(c - b'0')).min(CLAMP);
                prev_underscore = false;
            } else if c == b'_' && digits > 0 && !prev_underscore {
                prev_underscore = true;
            } else {
                break;
            }
            i += 1;
        }
        if digits == 0 || prev_underscore || digits > 4300 {
            return None;
        }
        while i < ascii.len() && is_space(ascii[i]) {
            i += 1;
        }
        if i != ascii.len() {
            return None;
        }
        Some(if neg { -value } else { value })
    }
}

// ---------------------------------------------------------------------------
// base64url_decode (PyJWT utils) on top of binascii.a2b_base64(strict=False)
// ---------------------------------------------------------------------------

mod b64lenient {
    fn sextet(c: u8) -> Option<u8> {
        match c {
            b'A'..=b'Z' => Some(c - b'A'),
            b'a'..=b'z' => Some(c - b'a' + 26),
            b'0'..=b'9' => Some(c - b'0' + 52),
            b'+' | b'-' => Some(62),
            b'/' | b'_' => Some(63),
            _ => None,
        }
    }

    /// `base64url_decode(utf8_bytes)`: pad to a multiple of four with `=`,
    /// map `-_` to `+/`, then `binascii.a2b_base64(strict_mode=False)` as in
    /// CPython 3.14: foreign characters and `=` are skipped wherever they
    /// appear, and a trailing partial quantum needs enough `=` after the last
    /// data character. `None` is a `binascii.Error`.
    pub(super) fn base64url_decode(input: &[u8]) -> Option<Vec<u8>> {
        let mut data = input.to_vec();
        let rem = data.len() % 4;
        if rem > 0 {
            data.extend(std::iter::repeat_n(b'=', 4 - rem));
        }
        let mut out = Vec::with_capacity(data.len() / 4 * 3);
        let (mut quad_pos, mut left, mut pads) = (0usize, 0u8, 0usize);
        for &ch in &data {
            if ch == b'=' {
                pads += 1;
                continue;
            }
            let Some(v) = sextet(ch) else { continue };
            pads = 0;
            match quad_pos {
                0 => {
                    quad_pos = 1;
                    left = v;
                }
                1 => {
                    quad_pos = 2;
                    out.push((left << 2) | (v >> 4));
                    left = v & 0x0f;
                }
                2 => {
                    quad_pos = 3;
                    out.push((left << 4) | (v >> 2));
                    left = v & 0x03;
                }
                _ => {
                    quad_pos = 0;
                    out.push((left << 6) | v);
                    left = 0;
                }
            }
        }
        match quad_pos {
            0 => Some(out),
            1 => None,
            q if q + pads >= 4 => Some(out),
            _ => None,
        }
    }
}

// ---------------------------------------------------------------------------
// json.loads(bytes) as CPython 3.14 does it (C scanner)
// ---------------------------------------------------------------------------

pub(crate) mod pyjson {
    use super::*;

    /// A Python `str`: code points, lone surrogates included.
    #[derive(Debug, Clone, PartialEq, Eq, Hash)]
    pub struct PyStr(Vec<u32>);

    impl PyStr {
        pub fn new(s: &str) -> Self {
            PyStr(s.chars().map(u32::from).collect())
        }

        pub fn code_points(&self) -> &[u32] {
            &self.0
        }

        pub fn is_empty(&self) -> bool {
            self.0.is_empty()
        }

        pub fn eq_str(&self, s: &str) -> bool {
            self.0.iter().copied().eq(s.chars().map(u32::from))
        }

        /// `None` when the string holds lone surrogates.
        pub fn as_string(&self) -> Option<String> {
            self.0.iter().map(|&c| char::from_u32(c)).collect()
        }

        /// Lone surrogates rendered as U+FFFD.
        pub fn to_string_lossy(&self) -> String {
            self.0
                .iter()
                .map(|&c| char::from_u32(c).unwrap_or('\u{FFFD}'))
                .collect()
        }

        /// `str.encode("utf-8")`; `None` is a UnicodeEncodeError.
        pub fn to_utf8(&self) -> Option<Vec<u8>> {
            self.as_string().map(String::into_bytes)
        }
    }

    #[derive(Debug, Clone, PartialEq)]
    pub enum Value {
        Null,
        Bool(bool),
        /// Clamped to ±1e36 (see `pyint::CLAMP`); the 4300-digit limit is
        /// enforced while parsing.
        Int(i128),
        Float(f64),
        Str(PyStr),
        List(Vec<Value>),
        Dict(IndexMap<PyStr, Value>),
    }

    impl Value {
        pub fn truthy(&self) -> bool {
            match self {
                Value::Null => false,
                Value::Bool(b) => *b,
                Value::Int(i) => *i != 0,
                Value::Float(f) => *f != 0.0,
                Value::Str(s) => !s.is_empty(),
                Value::List(l) => !l.is_empty(),
                Value::Dict(d) => !d.is_empty(),
            }
        }

        pub fn type_name(&self) -> &'static str {
            match self {
                Value::Null => "NoneType",
                Value::Bool(_) => "bool",
                Value::Int(_) => "int",
                Value::Float(_) => "float",
                Value::Str(_) => "str",
                Value::List(_) => "list",
                Value::Dict(_) => "dict",
            }
        }

        /// `dict.get(key)` (None for non-dicts or a missing key).
        pub fn get_str(&self, key: &str) -> Option<&Value> {
            match self {
                Value::Dict(d) => d.get(&PyStr::new(key)),
                _ => None,
            }
        }
    }

    // --- bytes -> str (json.detect_encoding + decode(..., 'surrogatepass')) --

    fn decode_error(codec: &str, data: &[u8], start: usize, end: usize, reason: &str) -> String {
        if end - start == 1 {
            format!(
                "'{codec}' codec can't decode byte 0x{:02x} in position {start}: {reason}",
                data[start]
            )
        } else {
            format!(
                "'{codec}' codec can't decode bytes in position {start}-{}: {reason}",
                end - 1
            )
        }
    }

    fn decode_utf8(data: &[u8]) -> R<Vec<u32>> {
        let mut out = Vec::with_capacity(data.len());
        let n = data.len();
        let mut i = 0;
        while i < n {
            let b = data[i];
            if b < 0x80 {
                out.push(u32::from(b));
                i += 1;
                continue;
            }
            let (need, lo, hi) = match b {
                0xC2..=0xDF => (1, 0x80, 0xBF),
                0xE0 => (2, 0xA0, 0xBF),
                0xE1..=0xEC | 0xEE..=0xEF => (2, 0x80, 0xBF),
                0xED => (2, 0x80, 0x9F),
                0xF0 => (3, 0x90, 0xBF),
                0xF1..=0xF3 => (3, 0x80, 0xBF),
                0xF4 => (3, 0x80, 0x8F),
                _ => (0, 0, 0),
            };
            let mut err: Option<(usize, &str)> = None;
            if need == 0 {
                err = Some((i + 1, "invalid start byte"));
            } else {
                for k in 1..=need {
                    if i + k >= n {
                        err = Some((n, "unexpected end of data"));
                        break;
                    }
                    let c = data[i + k];
                    let (l, h) = if k == 1 { (lo, hi) } else { (0x80, 0xBF) };
                    if !(l..=h).contains(&c) {
                        err = Some((i + k, "invalid continuation byte"));
                        break;
                    }
                }
            }
            match err {
                None => {
                    let mut cp = u32::from(b) & (0x7F >> (need + 1));
                    for k in 1..=need {
                        cp = (cp << 6) | (u32::from(data[i + k]) & 0x3F);
                    }
                    out.push(cp);
                    i += need + 1;
                }
                Some((end, reason)) => {
                    // surrogatepass: an encoded surrogate (ED A0..BF xx).
                    if i + 2 < n && b & 0xF0 == 0xE0 && data[i + 1] & 0xC0 == 0x80 && data[i + 2] & 0xC0 == 0x80 {
                        let cp = ((u32::from(b) & 0x0F) << 12)
                            | ((u32::from(data[i + 1]) & 0x3F) << 6)
                            | (u32::from(data[i + 2]) & 0x3F);
                        if (0xD800..=0xDFFF).contains(&cp) {
                            out.push(cp);
                            i += 3;
                            continue;
                        }
                    }
                    return Err(decode_error("utf-8", data, i, end, reason));
                }
            }
        }
        Ok(out)
    }

    fn decode_utf16(data: &[u8], start: usize, big: bool) -> R<Vec<u32>> {
        let codec = if big { "utf-16-be" } else { "utf-16-le" };
        let unit = |i: usize| -> u32 {
            let (a, b) = (u32::from(data[i]), u32::from(data[i + 1]));
            if big { (a << 8) | b } else { (b << 8) | a }
        };
        let mut out = Vec::new();
        let mut i = start;
        while i < data.len() {
            if i + 1 >= data.len() {
                return Err(decode_error(codec, data, i, data.len(), "truncated data"));
            }
            let u = unit(i);
            if (0xD800..=0xDBFF).contains(&u) && i + 3 < data.len() {
                let u2 = unit(i + 2);
                if (0xDC00..=0xDFFF).contains(&u2) {
                    out.push(0x10000 + ((u - 0xD800) << 10) + (u2 - 0xDC00));
                    i += 4;
                    continue;
                }
            }
            out.push(u);
            i += 2;
        }
        Ok(out)
    }

    fn decode_utf32(data: &[u8], start: usize, big: bool) -> R<Vec<u32>> {
        let codec = if big { "utf-32-be" } else { "utf-32-le" };
        let mut out = Vec::new();
        let mut i = start;
        while i < data.len() {
            if i + 4 > data.len() {
                return Err(decode_error(codec, data, i, data.len(), "truncated data"));
            }
            let b = [data[i], data[i + 1], data[i + 2], data[i + 3]];
            let cp = if big {
                u32::from_be_bytes(b)
            } else {
                u32::from_le_bytes(b)
            };
            if cp > 0x10FFFF {
                return Err(decode_error(codec, data, i, i + 4, "code point not in range(0x110000)"));
            }
            out.push(cp);
            i += 4;
        }
        Ok(out)
    }

    /// `bytes.decode(json.detect_encoding(b), 'surrogatepass')`.
    pub(crate) fn decode_bytes(b: &[u8]) -> R<Vec<u32>> {
        if b.starts_with(&[0, 0, 0xFE, 0xFF]) {
            return decode_utf32(b, 4, true);
        }
        if b.starts_with(&[0xFF, 0xFE, 0, 0]) {
            return decode_utf32(b, 4, false);
        }
        if b.starts_with(&[0xFE, 0xFF]) {
            return decode_utf16(b, 2, true);
        }
        if b.starts_with(&[0xFF, 0xFE]) {
            return decode_utf16(b, 2, false);
        }
        if b.starts_with(&[0xEF, 0xBB, 0xBF]) {
            return decode_utf8(&b[3..]);
        }
        if b.len() >= 4 {
            if b[0] == 0 {
                return if b[1] != 0 {
                    decode_utf16(b, 0, true)
                } else {
                    decode_utf32(b, 0, true)
                };
            }
            if b[1] == 0 {
                return if b[2] != 0 || b[3] != 0 {
                    decode_utf16(b, 0, false)
                } else {
                    decode_utf32(b, 0, false)
                };
            }
        } else if b.len() == 2 {
            if b[0] == 0 {
                return decode_utf16(b, 0, true);
            }
            if b[1] == 0 {
                return decode_utf16(b, 0, false);
            }
        }
        decode_utf8(b)
    }

    // --- scanner ------------------------------------------------------------

    fn err_at(s: &[u32], msg: &str, pos: usize) -> String {
        let line = s[..pos].iter().filter(|&&c| c == 0x0A).count() + 1;
        let col = match s[..pos].iter().rposition(|&c| c == 0x0A) {
            Some(nl) => pos - nl,
            None => pos + 1,
        };
        format!("{msg}: line {line} column {col} (char {pos})")
    }

    fn is_ws(c: u32) -> bool {
        matches!(c, 0x20 | 0x09 | 0x0A | 0x0D)
    }

    fn skip_ws(s: &[u32], mut i: usize) -> usize {
        while i < s.len() && is_ws(s[i]) {
            i += 1;
        }
        i
    }

    fn at(s: &[u32], i: usize) -> Option<u32> {
        s.get(i).copied()
    }

    fn hex4(s: &[u32], i: usize) -> Option<u32> {
        if i + 4 > s.len() {
            return None;
        }
        let mut v = 0;
        for &c in &s[i..i + 4] {
            let d = char::from_u32(c)?.to_digit(16)?;
            v = (v << 4) | d;
        }
        Some(v)
    }

    /// `scanstring(s, end)` where `end` follows the opening quote.
    fn scanstring(s: &[u32], mut end: usize) -> R<(PyStr, usize)> {
        let begin = end - 1;
        let mut out = Vec::new();
        loop {
            let mut j = end;
            while j < s.len() && s[j] != u32::from(b'"') && s[j] != u32::from(b'\\') && s[j] > 0x1F {
                j += 1;
            }
            if j == s.len() {
                return Err(err_at(s, "Unterminated string starting at", begin));
            }
            out.extend_from_slice(&s[end..j]);
            let t = s[j];
            end = j + 1;
            if t == u32::from(b'"') {
                break;
            }
            if t != u32::from(b'\\') {
                return Err(err_at(s, "Invalid control character at", j));
            }
            let Some(esc) = at(s, end) else {
                return Err(err_at(s, "Unterminated string starting at", begin));
            };
            if esc != u32::from(b'u') {
                let c = match char::from_u32(esc) {
                    Some('"') => '"',
                    Some('\\') => '\\',
                    Some('/') => '/',
                    Some('b') => '\u{8}',
                    Some('f') => '\u{c}',
                    Some('n') => '\n',
                    Some('r') => '\r',
                    Some('t') => '\t',
                    _ => return Err(err_at(s, "Invalid \\escape", end - 1)),
                };
                out.push(u32::from(c));
                end += 1;
            } else {
                let mut uni = hex4(s, end + 1).ok_or_else(|| err_at(s, "Invalid \\uXXXX escape", end))?;
                end += 5;
                if (0xD800..=0xDBFF).contains(&uni)
                    && at(s, end) == Some(u32::from(b'\\'))
                    && at(s, end + 1) == Some(u32::from(b'u'))
                {
                    let uni2 = hex4(s, end + 2).ok_or_else(|| err_at(s, "Invalid \\uXXXX escape", end + 1))?;
                    if (0xDC00..=0xDFFF).contains(&uni2) {
                        uni = 0x10000 + (((uni - 0xD800) << 10) | (uni2 - 0xDC00));
                        end += 6;
                    }
                }
                out.push(uni);
            }
        }
        Ok((PyStr(out), end))
    }

    fn starts_with_at(s: &[u32], i: usize, lit: &str) -> bool {
        let lit: Vec<u32> = lit.chars().map(u32::from).collect();
        s.len() >= i + lit.len() && s[i..i + lit.len()] == lit[..]
    }

    /// `_match_number_unicode`: `Ok(None)` is StopIteration (no value here).
    fn match_number(s: &[u32], start: usize) -> R<Option<(Value, usize)>> {
        let digit = |i: usize| s.get(i).is_some_and(|&c| (0x30..=0x39).contains(&c));
        let mut idx = start;
        if at(s, idx) == Some(u32::from(b'-')) {
            idx += 1;
            if idx >= s.len() {
                return Ok(None);
            }
        }
        match at(s, idx) {
            Some(c) if (0x31..=0x39).contains(&c) => {
                idx += 1;
                while digit(idx) {
                    idx += 1;
                }
            }
            Some(0x30) => idx += 1,
            _ => return Ok(None),
        }
        let mut is_float = false;
        if at(s, idx) == Some(u32::from(b'.')) && digit(idx + 1) {
            is_float = true;
            idx += 2;
            while digit(idx) {
                idx += 1;
            }
        }
        if matches!(at(s, idx), Some(0x65 | 0x45)) && idx + 1 < s.len() {
            let e_start = idx;
            idx += 1;
            if matches!(at(s, idx), Some(0x2B | 0x2D)) && idx + 1 < s.len() {
                idx += 1;
            }
            while digit(idx) {
                idx += 1;
            }
            if digit(idx - 1) {
                is_float = true;
            } else {
                idx = e_start;
            }
        }
        let text: String = s[start..idx]
            .iter()
            .map(|&c| char::from_u32(c).unwrap_or('0'))
            .collect();
        if is_float {
            return Ok(Some((Value::Float(text.parse::<f64>().unwrap_or(f64::NAN)), idx)));
        }
        let (neg, digits) = match text.strip_prefix('-') {
            Some(d) => (true, d),
            None => (false, text.as_str()),
        };
        if digits.len() > 4300 {
            return Err(format!(
                "Exceeds the limit (4300 digits) for integer string conversion: value has {} digits; use sys.set_int_max_str_digits() to increase the limit",
                digits.len()
            ));
        }
        let mut v: i128 = 0;
        for c in digits.bytes() {
            v = (v * 10 + i128::from(c - b'0')).min(pyint::CLAMP);
        }
        Ok(Some((Value::Int(if neg { -v } else { v }), idx)))
    }

    enum Frame {
        List(Vec<Value>),
        Dict(IndexMap<PyStr, Value>, PyStr),
    }

    /// Reads `"key" :` at `i` (after any whitespace) and returns the index of
    /// the value that follows.
    fn object_key(s: &[u32], i: usize) -> R<(PyStr, usize)> {
        if at(s, i) != Some(u32::from(b'"')) {
            return Err(err_at(s, "Expecting property name enclosed in double quotes", i));
        }
        let (key, mut i) = scanstring(s, i + 1)?;
        i = skip_ws(s, i);
        if at(s, i) != Some(u32::from(b':')) {
            return Err(err_at(s, "Expecting ':' delimiter", i));
        }
        Ok((key, skip_ws(s, i + 1)))
    }

    /// `json.loads` on an already-decoded document. Iterative, so nesting
    /// depth is bounded by memory rather than the stack.
    pub(crate) fn parse(s: &[u32]) -> R<Value> {
        let mut stack: Vec<Frame> = Vec::new();
        let mut idx = skip_ws(s, 0);
        'value: loop {
            let expecting = |i: usize| err_at(s, "Expecting value", i);
            let (mut val, mut i) = match at(s, idx).and_then(char::from_u32) {
                None => return Err(expecting(idx)),
                Some('"') => {
                    let (st, e) = scanstring(s, idx + 1)?;
                    (Value::Str(st), e)
                }
                Some('{') => {
                    let i = skip_ws(s, idx + 1);
                    if at(s, i) == Some(u32::from(b'}')) {
                        (Value::Dict(IndexMap::new()), i + 1)
                    } else {
                        let (key, vi) = object_key(s, i)?;
                        stack.push(Frame::Dict(IndexMap::new(), key));
                        idx = vi;
                        continue 'value;
                    }
                }
                Some('[') => {
                    let i = skip_ws(s, idx + 1);
                    if at(s, i) == Some(u32::from(b']')) {
                        (Value::List(Vec::new()), i + 1)
                    } else {
                        stack.push(Frame::List(Vec::new()));
                        idx = i;
                        continue 'value;
                    }
                }
                Some(c) => {
                    let constant = match c {
                        'n' if starts_with_at(s, idx, "null") => Some((Value::Null, 4)),
                        't' if starts_with_at(s, idx, "true") => Some((Value::Bool(true), 4)),
                        'f' if starts_with_at(s, idx, "false") => Some((Value::Bool(false), 5)),
                        'N' if starts_with_at(s, idx, "NaN") => Some((Value::Float(f64::NAN), 3)),
                        'I' if starts_with_at(s, idx, "Infinity") => Some((Value::Float(f64::INFINITY), 8)),
                        '-' if starts_with_at(s, idx, "-Infinity") => Some((Value::Float(f64::NEG_INFINITY), 9)),
                        _ => None,
                    };
                    match constant {
                        Some((v, len)) => (v, idx + len),
                        None => match match_number(s, idx)? {
                            Some(v) => v,
                            None => return Err(expecting(idx)),
                        },
                    }
                }
            };
            loop {
                match stack.last_mut() {
                    None => {
                        let end = skip_ws(s, i);
                        if end != s.len() {
                            return Err(err_at(s, "Extra data", end));
                        }
                        return Ok(val);
                    }
                    Some(Frame::List(items)) => {
                        items.push(val);
                        i = skip_ws(s, i);
                        if at(s, i) == Some(u32::from(b']')) {
                            let Some(Frame::List(items)) = stack.pop() else {
                                unreachable!()
                            };
                            val = Value::List(items);
                            i += 1;
                            continue;
                        }
                        if at(s, i) != Some(u32::from(b',')) {
                            return Err(err_at(s, "Expecting ',' delimiter", i));
                        }
                        let comma = i;
                        i = skip_ws(s, i + 1);
                        if at(s, i) == Some(u32::from(b']')) {
                            return Err(err_at(s, "Illegal trailing comma before end of array", comma));
                        }
                        idx = i;
                        continue 'value;
                    }
                    Some(Frame::Dict(map, key)) => {
                        map.insert(std::mem::replace(key, PyStr(Vec::new())), val);
                        i = skip_ws(s, i);
                        if at(s, i) == Some(u32::from(b'}')) {
                            let Some(Frame::Dict(map, _)) = stack.pop() else {
                                unreachable!()
                            };
                            val = Value::Dict(map);
                            i += 1;
                            continue;
                        }
                        if at(s, i) != Some(u32::from(b',')) {
                            return Err(err_at(s, "Expecting ',' delimiter", i));
                        }
                        let comma = i;
                        i = skip_ws(s, i + 1);
                        if at(s, i) == Some(u32::from(b'}')) {
                            return Err(err_at(s, "Illegal trailing comma before end of object", comma));
                        }
                        let (k, vi) = object_key(s, i)?;
                        *key = k;
                        idx = vi;
                        continue 'value;
                    }
                }
            }
        }
    }

    /// `json.loads(data)` for `bytes`.
    pub fn loads(data: &[u8]) -> R<Value> {
        parse(&decode_bytes(data)?)
    }
}

#[cfg(test)]
mod tests {
    use std::collections::HashMap;

    use wiremock::matchers::any;
    use wiremock::{Mock, MockServer, Request, Respond, ResponseTemplate};

    use super::*;

    fn testdata(name: &str) -> serde_json::Value {
        let path = format!("{}/testdata/oidc/{name}", env!("CARGO_MANIFEST_DIR"));
        let text = std::fs::read_to_string(&path).unwrap_or_else(|e| panic!("read {path}: {e}"));
        serde_json::from_str(&text).expect("fixture is JSON")
    }

    struct FakeClock(StdMutex<(f64, f64)>);

    impl FakeClock {
        fn new() -> Arc<Self> {
            Arc::new(Self(StdMutex::new((0.0, 0.0))))
        }

        fn set(&self, now: f64, mono: f64) {
            *self.0.lock().unwrap() = (now, mono);
        }
    }

    impl Clock for FakeClock {
        fn now(&self) -> f64 {
            self.0.lock().unwrap().0
        }

        fn monotonic(&self) -> f64 {
            self.0.lock().unwrap().1
        }
    }

    type Route = (u16, Vec<u8>, Vec<(String, String)>);

    /// Programmable IdP: routes are swapped between steps, requests counted.
    #[derive(Clone, Default)]
    struct Idp {
        routes: Arc<StdMutex<HashMap<String, Route>>>,
        counts: Arc<StdMutex<HashMap<String, u64>>>,
    }

    impl Respond for Idp {
        fn respond(&self, req: &Request) -> ResponseTemplate {
            let path = req.url.path().to_string();
            *self.counts.lock().unwrap().entry(path.clone()).or_default() += 1;
            let (status, body, headers) =
                self.routes
                    .lock()
                    .unwrap()
                    .get(&path)
                    .cloned()
                    .unwrap_or((404, Vec::new(), Vec::new()));
            let mut t = ResponseTemplate::new(status).set_body_bytes(body);
            for (k, v) in headers {
                t = t.insert_header(k.as_str(), v.as_str());
            }
            t
        }
    }

    impl Idp {
        fn set_routes(&self, spec: &serde_json::Value, bodies: &HashMap<String, Vec<u8>>) {
            let mut routes = self.routes.lock().unwrap();
            routes.clear();
            for (path, r) in spec.as_object().expect("routes object") {
                let headers = r["headers"]
                    .as_object()
                    .map(|h| {
                        h.iter()
                            .map(|(k, v)| (k.clone(), v.as_str().unwrap().to_string()))
                            .collect()
                    })
                    .unwrap_or_default();
                let body = bodies[r["body"].as_str().unwrap()].clone();
                routes.insert(path.clone(), (r["status"].as_u64().unwrap() as u16, body, headers));
            }
        }
    }

    async fn idp_server() -> (MockServer, Idp, reqwest::Client) {
        let server = MockServer::start().await;
        let idp = Idp::default();
        Mock::given(any()).respond_with(idp.clone()).mount(&server).await;
        let http = http_client_builder()
            .resolve("idp.test", *server.address())
            .build()
            .unwrap();
        (server, idp, http)
    }

    /// What the Rust port returns for a claim set Python accepted: claims
    /// holding non-strings or lone surrogates cannot become `TokenClaims`.
    fn expected_outcome(ok: &serde_json::Value) -> Result<TokenClaims, String> {
        let field = |name: &str, claim: &str| -> Result<Option<String>, String> {
            match &ok[name] {
                serde_json::Value::Null => Ok(None),
                serde_json::Value::String(s) => Ok(Some(s.clone())),
                serde_json::Value::Object(o) if o.contains_key("nonstr") => {
                    Err(format!("Token validation failed: {claim} claim must be a string"))
                }
                serde_json::Value::Object(_) => {
                    Err(format!("Token validation failed: {claim} claim is not valid Unicode"))
                }
                other => panic!("unexpected claim fixture {other}"),
            }
        };
        let issuer = field("issuer", "iss")?.expect("issuer");
        let subject = field("subject", "sub")?.expect("subject");
        let email = field("email", "email")?;
        let name = field("name", "name")?;
        Ok(TokenClaims {
            issuer,
            subject,
            email,
            name,
            email_verified: ok["email_verified"].as_bool().unwrap(),
        })
    }

    /// Replays every case recorded from the Python validator (PyJWT 2.15)
    /// against a local IdP with the same pinned clocks.
    #[tokio::test]
    async fn differential_against_pyjwt() {
        let fx = testdata("scenarios.json");
        let bodies: HashMap<String, Vec<u8>> = fx["bodies"]
            .as_object()
            .unwrap()
            .iter()
            .map(|(k, v)| {
                (
                    k.clone(),
                    base64::engine::general_purpose::STANDARD
                        .decode(v.as_str().unwrap())
                        .unwrap(),
                )
            })
            .collect();
        let (_server, idp, http) = idp_server().await;
        let mut failures = Vec::new();
        let mut steps = 0;
        for sc in fx["scenarios"].as_array().unwrap() {
            let name = sc["name"].as_str().unwrap();
            let cfg = &sc["config"];
            idp.set_routes(&sc["routes"], &bodies);
            idp.counts.lock().unwrap().clear();
            let clock = FakeClock::new();
            let validator = OidcTokenValidator::with_http_and_clock(
                cfg["issuer_url"].as_str().unwrap(),
                cfg["client_id"].as_str().unwrap(),
                cfg["audience"].as_str().unwrap(),
                cfg["leeway"].as_i64().unwrap(),
                http.clone(),
                clock.clone(),
            );
            for (i, step) in sc["steps"].as_array().unwrap().iter().enumerate() {
                steps += 1;
                if let Some(r) = step.get("routes") {
                    idp.set_routes(r, &bodies);
                }
                clock.set(step["now"].as_f64().unwrap(), step["mono"].as_f64().unwrap());
                let got = validator.validate(step["token"].as_str().unwrap()).await;
                let expect = &step["expect"];
                let want: Result<TokenClaims, String> = match expect.get("ok") {
                    Some(ok) => expected_outcome(ok),
                    None => Err(expect["err"].as_str().unwrap().to_string()),
                };
                let got = got.map_err(|e| {
                    assert_eq!((e.kind, e.code), (ErrorKind::TokenValidation, 401));
                    e.message
                });
                if got != want {
                    failures.push(format!("[{name} #{i}]\n   want {want:?}\n    got {got:?}"));
                }
                let want_counts: HashMap<String, u64> = step["requests"]
                    .as_object()
                    .unwrap()
                    .iter()
                    .map(|(k, v)| (k.clone(), v.as_u64().unwrap()))
                    .collect();
                let got_counts = idp.counts.lock().unwrap().clone();
                if got_counts != want_counts {
                    failures.push(format!(
                        "[{name} #{i}] requests want {want_counts:?} got {got_counts:?}"
                    ));
                }
            }
        }
        assert!(
            failures.is_empty(),
            "{} mismatches over {steps} steps:\n{}",
            failures.len(),
            failures.join("\n")
        );
        assert!(steps > 500, "fixture unexpectedly small: {steps}");
    }

    fn canon(v: &Value) -> String {
        match v {
            Value::Null => "N".into(),
            Value::Bool(true) => "T".into(),
            Value::Bool(false) => "F".into(),
            Value::Int(i) => format!("I{i}"),
            Value::Float(f) if f.is_nan() => "Dnan".into(),
            Value::Float(f) => format!("D{}", hex::encode(f.to_be_bytes())),
            Value::Str(s) => format!(
                "S{}",
                s.code_points()
                    .iter()
                    .map(|c| format!("{c:x}"))
                    .collect::<Vec<_>>()
                    .join(",")
            ),
            Value::List(items) => format!("[{}]", items.iter().map(canon).collect::<Vec<_>>().join(";")),
            Value::Dict(d) => format!(
                "{{{}}}",
                d.iter()
                    .map(|(k, v)| format!("{}:{}", canon(&Value::Str(k.clone())), canon(v)))
                    .collect::<Vec<_>>()
                    .join(";")
            ),
        }
    }

    /// `json.loads(bytes)`: values and exact error texts, from a fuzzed
    /// corpus recorded with CPython 3.14.
    #[test]
    fn json_loads_matches_cpython() {
        let fx = testdata("primitives.json");
        let mut failures = Vec::new();
        let cases = fx["json"].as_array().unwrap();
        for case in cases {
            let input = hex::decode(case["in"].as_str().unwrap()).unwrap();
            let got = pyjson::loads(&input).map(|v| canon(&v));
            let want = match case.get("out") {
                Some(o) => Ok(o.as_str().unwrap().to_string()),
                None => Err(case["err"].as_str().unwrap().to_string()),
            };
            if got != want {
                failures.push(format!("{}: want {want:?} got {got:?}", case["in"]));
            }
        }
        assert!(
            failures.is_empty(),
            "{}/{} json cases differ:\n{}",
            failures.len(),
            cases.len(),
            failures.join("\n")
        );
    }

    /// `int(value)` for claim values.
    #[test]
    fn int_matches_cpython() {
        let fx = testdata("primitives.json");
        let mut failures = Vec::new();
        for case in fx["int"].as_array().unwrap() {
            let text = case["in"].as_str().unwrap();
            let v = pyjson::loads(text.as_bytes()).unwrap();
            let got = pyint::int(&v).map(|i| i.to_string());
            let want = case["out"].as_str().map(str::to_string);
            if got != want {
                failures.push(format!("{text}: want {want:?} got {got:?}"));
            }
        }
        assert!(failures.is_empty(), "{}", failures.join("\n"));
    }

    /// PyJWT's lenient `base64url_decode` used for JWK members.
    #[test]
    fn base64url_decode_matches_pyjwt() {
        let fx = testdata("primitives.json");
        let mut failures = Vec::new();
        for case in fx["b64"].as_array().unwrap() {
            let input = case["in"].as_str().unwrap();
            let got = b64lenient::base64url_decode(input.as_bytes()).map(hex::encode);
            let want = case["out"].as_str().map(str::to_string);
            if got != want {
                failures.push(format!("{input:?}: want {want:?} got {got:?}"));
            }
        }
        assert!(failures.is_empty(), "{}", failures.join("\n"));
    }

    #[test]
    fn build_validator_is_disabled_without_issuer() {
        let mut cfg = OidcConfig {
            issuer_url: String::new(),
            client_id: "web".into(),
            audience: String::new(),
            scope: OidcConfig::DEFAULT_OIDC_SCOPE.into(),
            clock_skew_seconds: 60,
        };
        assert!(build_validator(&cfg).is_none());
        cfg.issuer_url = "https://idp.example//".into();
        let v = build_validator(&cfg).expect("enabled");
        assert_eq!(v.issuer, "https://idp.example");
        assert_eq!(v.audiences, vec!["web".to_string(), "api://web".to_string()]);
        assert_eq!(v.leeway, 60);
        cfg.audience = "api://kumoss".into();
        assert_eq!(
            build_validator(&cfg).unwrap().audiences,
            vec!["api://kumoss".to_string()]
        );
    }

    /// Discovery is lazy, derived from the issuer without its trailing
    /// slashes, retried after a failure and then kept.
    #[tokio::test]
    async fn discovery_is_lazy_and_cached() {
        let server = MockServer::start().await;
        let idp = Idp::default();
        Mock::given(any()).respond_with(idp.clone()).mount(&server).await;
        let issuer = format!("{}//", server.uri());
        let v = OidcTokenValidator::with_http_and_clock(
            &issuer,
            "web",
            "",
            60,
            http_client_builder().build().unwrap(),
            FakeClock::new(),
        );
        assert!(idp.counts.lock().unwrap().is_empty(), "no request before first use");
        let err = v.validate("a.b.c").await.unwrap_err();
        assert!(
            err.message
                .starts_with("Token validation failed: Client error '404 Not Found' for url '"),
            "{}",
            err.message
        );
        let doc = format!(r#"{{"jwks_uri":"{}/jwks"}}"#, server.uri());
        idp.routes.lock().unwrap().insert(
            "/.well-known/openid-configuration".into(),
            (200, doc.into_bytes(), vec![]),
        );
        let err = v.validate("a.b.c").await.unwrap_err();
        assert_eq!(err.message, "Token validation failed: Invalid header padding");
        let _ = v.validate("x").await;
        assert_eq!(idp.counts.lock().unwrap()["/.well-known/openid-configuration"], 2);
        assert!(!idp.counts.lock().unwrap().contains_key("/jwks"));
    }
}
