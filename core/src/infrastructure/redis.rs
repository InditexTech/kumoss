// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

//! Minimal async Redis client for caching and session state.
//!
//! The database is the source of truth; Redis being down must never take
//! reads down with it. Every operation is fail-open: an error (or a call
//! slower than `socket_timeout`) is logged and surfaces as a cache miss or
//! a skipped write, never as an error to the caller.

use std::collections::HashMap;
use std::sync::{Arc, Mutex};
use std::time::Duration;

use redis::aio::{ConnectionManager, ConnectionManagerConfig};
use serde_json::Value;

use crate::shared::config::RedisConfig;
use crate::shared::error::{AppError, AppResult};
use crate::shared::pyfmt;

/// How a `get_or_set` miss picks the expiry of what it loaded.
pub enum Ttl<'a> {
    Fixed(u64),
    /// Receives the loaded value, so read-repair can keep values that can
    /// never change for longer.
    From(&'a (dyn Fn(&Value) -> u64 + Send + Sync)),
}

/// A key's load lock and the number of callers holding it.
type LoadSlot = (Arc<tokio::sync::Mutex<()>>, usize);

#[derive(Clone)]
pub struct RedisCache {
    conn: Option<ConnectionManager>,
    timeout: Duration,
    /// Per-key single-flight registry: key -> lock.
    loading: Arc<Mutex<HashMap<String, LoadSlot>>>,
}

impl RedisCache {
    /// Connect and verify connectivity with a PING.
    pub async fn initialize(cfg: &RedisConfig) -> AppResult<Self> {
        let fail = |e: String| {
            tracing::error!("Failed to initialize redis connection manager: {e}");
            AppError::new(format!("Failed to initialize redis: {e}"), 500)
        };
        let client = redis::Client::open(cfg.redis_url()).map_err(|e| fail(e.to_string()))?;
        let manager_cfg = ConnectionManagerConfig::new()
            .set_connection_timeout(Duration::from_secs_f64(cfg.socket_connect_timeout))
            .set_response_timeout(Duration::from_secs_f64(cfg.socket_timeout))
            .set_number_of_retries(2)
            .set_max_delay(500);
        let mut conn = tokio::time::timeout(
            Duration::from_secs_f64(cfg.socket_connect_timeout + cfg.pool_timeout),
            ConnectionManager::new_with_config(client, manager_cfg),
        )
        .await
        .map_err(|_| fail("Timeout connecting to server".into()))?
        .map_err(|e| fail(e.to_string()))?;
        let pong: String = redis::cmd("PING")
            .query_async(&mut conn)
            .await
            .map_err(|e| fail(e.to_string()))?;
        let _ = pong;
        tracing::info!("Redis connection manager initialized successfully");
        Ok(Self {
            conn: Some(conn),
            timeout: Duration::from_secs_f64(cfg.socket_timeout + cfg.pool_timeout),
            loading: Arc::new(Mutex::new(HashMap::new())),
        })
    }

    /// A cache that is always empty and drops every write (tests, tools).
    pub fn disabled() -> Self {
        Self {
            conn: None,
            timeout: Duration::from_secs(1),
            loading: Arc::new(Mutex::new(HashMap::new())),
        }
    }

    async fn run<T: redis::FromRedisValue>(&self, cmd: &redis::Cmd) -> Result<T, String> {
        let Some(conn) = &self.conn else {
            return Err("redis not initialized".into());
        };
        let mut conn = conn.clone();
        match tokio::time::timeout(self.timeout, cmd.query_async::<T>(&mut conn)).await {
            Ok(Ok(v)) => Ok(v),
            Ok(Err(e)) => Err(e.to_string()),
            Err(_) => Err("Timeout reading from socket".into()),
        }
    }

    // --- fail-open primitives -------------------------------------------

    async fn safe_get(&self, key: &str) -> Option<String> {
        self.conn.as_ref()?;
        match self.run::<Option<String>>(redis::cmd("GET").arg(key)).await {
            Ok(v) => v,
            Err(e) => {
                tracing::warn!("Redis GET {key} failed ({e}); treating as a miss");
                None
            }
        }
    }

    async fn safe_set(&self, key: &str, encoded: &str, ttl: Option<u64>, nx: bool) {
        if self.conn.is_none() {
            return;
        }
        let mut cmd = redis::cmd("SET");
        cmd.arg(key).arg(encoded);
        if let Some(ttl) = ttl {
            cmd.arg("EX").arg(ttl);
        }
        if nx {
            cmd.arg("NX");
        }
        if let Err(e) = self.run::<redis::Value>(&cmd).await {
            tracing::warn!("Redis SET {key} failed ({e}); value not cached, stale reads possible until TTL");
        }
    }

    /// JSON-decode a cached entry; a corrupt entry is dropped as a miss
    /// (it must be deleted: SET NX would otherwise never repair the key).
    async fn decode(&self, key: &str, raw: &str) -> Option<Value> {
        match serde_json::from_str::<Value>(raw) {
            Ok(v) => Some(v),
            Err(_) => {
                tracing::warn!("Corrupt cache entry at {key}; dropping it");
                self.invalidate(&[key]).await;
                None
            }
        }
    }

    // --- JSON values -------------------------------------------------------

    /// Fail-open read of the JSON value at `key` (`None` if absent).
    pub async fn get_json(&self, key: &str) -> Option<Value> {
        let raw = self.safe_get(key).await?;
        self.decode(key, &raw).await
    }

    /// Write-through: overwrite unconditionally.
    pub async fn set_json(&self, key: &str, value: &Value, ttl: Option<u64>) {
        self.safe_set(key, &pyfmt::json_dumps(value), ttl, false).await;
    }

    /// Write-through several `(key, value, ttl)` entries in one round trip.
    pub async fn set_json_many(&self, entries: &[(String, Value, Option<u64>)]) {
        let Some(conn) = &self.conn else {
            return;
        };
        let mut pipe = redis::pipe();
        for (key, value, ttl) in entries {
            let cmd = pipe.cmd("SET").arg(key).arg(pyfmt::json_dumps(value));
            if let Some(ttl) = ttl {
                cmd.arg("EX").arg(*ttl);
            }
            cmd.ignore();
        }
        let mut conn = conn.clone();
        let outcome = tokio::time::timeout(self.timeout, pipe.query_async::<()>(&mut conn)).await;
        let err = match outcome {
            Ok(Ok(())) => None,
            Ok(Err(e)) => Some(e.to_string()),
            Err(_) => Some("Timeout reading from socket".to_string()),
        };
        if let Some(e) = err {
            let keys: Vec<&str> = entries.iter().map(|(k, _, _)| k.as_str()).collect();
            tracing::warn!(
                "Redis pipelined SET [{}] failed ({e}); values not cached, stale reads possible until TTL",
                keys.join(", ")
            );
        }
    }

    /// Cache-aside: the JSON value at `key`, or `loader`'s.
    ///
    /// Misses for the same key are single-flighted per process; the miss
    /// path stores with SET NX so a fresher write-through is never
    /// clobbered; `None` (or JSON null) is never cached; hits and misses
    /// both return the JSON round-trip of the value.
    pub async fn get_or_set<F, Fut>(&self, key: &str, ttl: Ttl<'_>, loader: F) -> AppResult<Option<Value>>
    where
        F: FnOnce() -> Fut,
        Fut: std::future::Future<Output = AppResult<Option<Value>>>,
    {
        if let Some(raw) = self.safe_get(key).await
            && let Some(v) = self.decode(key, &raw).await
            && !v.is_null()
        {
            return Ok(Some(v));
        }

        let lock = {
            let mut loading = self.loading.lock().expect("loading lock");
            let entry = loading
                .entry(key.to_string())
                .or_insert_with(|| (Arc::new(tokio::sync::Mutex::new(())), 0));
            entry.1 += 1;
            entry.0.clone()
        };
        let result = async {
            let _guard = lock.lock().await;
            if let Some(raw) = self.safe_get(key).await
                && let Some(v) = self.decode(key, &raw).await
                && !v.is_null()
            {
                return Ok(Some(v));
            }
            let value = loader().await?;
            let Some(value) = value.filter(|v| !v.is_null()) else {
                return Ok(None);
            };
            let encoded = pyfmt::json_dumps(&value);
            let expiry = match ttl {
                Ttl::Fixed(t) => t,
                Ttl::From(f) => f(&value),
            };
            self.safe_set(key, &encoded, Some(expiry), true).await;
            Ok(Some(serde_json::from_str(&encoded).unwrap_or(value)))
        }
        .await;
        {
            let mut loading = self.loading.lock().expect("loading lock");
            if let Some(entry) = loading.get_mut(key) {
                entry.1 -= 1;
                if entry.1 == 0 {
                    loading.remove(key);
                }
            }
        }
        result
    }

    /// Drop cached `keys` so the next read recomputes. Returns the count removed.
    pub async fn invalidate(&self, keys: &[&str]) -> i64 {
        if self.conn.is_none() || keys.is_empty() {
            return 0;
        }
        let mut cmd = redis::cmd("DEL");
        for k in keys {
            cmd.arg(*k);
        }
        match self.run::<i64>(&cmd).await {
            Ok(n) => n,
            Err(e) => {
                tracing::warn!(
                    "Redis DEL {} failed ({e}); stale entries possible until TTL",
                    keys.join(", ")
                );
                0
            }
        }
    }
}
