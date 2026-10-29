// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

//! Stateless DB helpers with a Redis read-through cache.
//!
//! Reads are served from Redis so every worker/replica shares one view and
//! the cache survives restarts. Two flavours:
//!
//! * write-once facts (id maps, workspace, provider, first query) never
//!   change after `create_session`, so they carry a long TTL and are
//!   populated write-through at creation;
//! * mutable reads (session context, history, last status, pull requests)
//!   are written through on every mutation and read-repaired with SET NX on
//!   a miss. Entries are never deleted on write: delete-on-write races
//!   cache-aside readers, while write-through + NX cannot go stale that
//!   way. The TTL is only a backstop for a lost write-through SET.
//!
//! A third flavour exists for FINISHED sessions: once a session's latest
//! status is terminal (FAILED) it can never change again —
//! `acquire_in_flight` enforces this — so the full detail aggregate is
//! cached and the last-status key gets a long TTL. The only mutation still
//! possible on a finished session is the admin `set_lock` toggle, which
//! drops the cached detail.
//!
//! Keys are namespaced and versioned so a schema change can drop
//! everything by bumping the prefix. Key names and JSON payloads are shared
//! with the deployed cache and must not change.

use std::sync::Arc;

use chrono::{DateTime, Utc};
use serde_json::{Map, Value, json};
use sqlx::postgres::PgRow;
use sqlx::{PgPool, Postgres, QueryBuilder, Row};
use uuid::Uuid;

use crate::domain::dto::{
    AdminSessionDetail, CodeChangeRef, ComplianceCheckRef, PaginatedSessionSummary, PullRequestRef, ReportRef,
    RoundDetail, SessionSummary, StatusEntry, TerraformPlanRef, WorkspaceRef,
};
use crate::domain::entities::{SessionContext, User};
use crate::domain::ports::ObjectStorage;
use crate::domain::value_objects::{ProviderFacts, Status, WorkspaceFacts};
use crate::infrastructure::database::{db_error, is_unique_violation};
use crate::infrastructure::redis::{RedisCache, Ttl};
use crate::shared::config::SystemConfig;
use crate::shared::constants::{OperationRole, OperationType, PanelRole, ReportType, SessionStatus, TerraformProvider};
use crate::shared::error::{AppError, AppResult, ErrorKind};
use crate::shared::pyfmt;
use crate::shared::serde_util::now_micros;

// --- cache configuration --------------------------------------------------------

const CACHE_NS: &str = "kumoss:v1";

const TTL_FACTS: u64 = 4 * 24 * 60 * 60;
const TTL_CONTEXT: u64 = 2 * 24 * 60 * 60;
const TTL_HISTORY: u64 = 2 * 24 * 60 * 60;
const TTL_STATUS: u64 = 5 * 60;
const TTL_PR: u64 = 7 * 24 * 60 * 60;
/// Finished-session aggregate; it embeds presigned artifact URLs, so
/// `storage.presign_expiry_seconds` must outlive it (+ jitter).
const TTL_DETAIL: u64 = 24 * 60 * 60;

/// Session-level end states: once latest, never changes again.
const TERMINAL: [SessionStatus; 1] = [SessionStatus::Failed];

/// Base TTL plus up to ~10% jitter.
fn ttl(base: u64) -> u64 {
    base + rand::random_range(0..=std::cmp::max(1, base / 10))
}

/// Terminal statuses never change: keep them as long as the facts.
fn status_ttl(status: SessionStatus) -> u64 {
    if TERMINAL.contains(&status) {
        ttl(TTL_FACTS)
    } else {
        ttl(TTL_STATUS)
    }
}

fn k_sid(id: &Uuid) -> String {
    format!("{CACHE_NS}:map:sid:{id}")
}
fn k_owner(id: &Uuid) -> String {
    format!("{CACHE_NS}:session:{id}:owner")
}
fn k_workspace(id: &Uuid) -> String {
    format!("{CACHE_NS}:session:{id}:workspace")
}
fn k_provider(id: &Uuid) -> String {
    format!("{CACHE_NS}:session:{id}:provider")
}
fn k_first_query(id: &Uuid) -> String {
    format!("{CACHE_NS}:session:{id}:first-query")
}
fn k_context(id: &Uuid) -> String {
    format!("{CACHE_NS}:session:{id}:ctx")
}
fn k_last_status(id: &Uuid) -> String {
    format!("{CACHE_NS}:session:{id}:status:last")
}
fn k_history(id: &Uuid) -> String {
    format!("{CACHE_NS}:session:{id}:history")
}
fn k_pull_requests(id: &Uuid) -> String {
    // v2: entries carry "number"; a new key keeps pre-change caches out.
    format!("{CACHE_NS}:session:{id}:prs:v2")
}
fn k_detail(id: &Uuid) -> String {
    format!("{CACHE_NS}:session:{id}:detail")
}

/// Reduce a SessionContext to the JSON-safe fields that rebuild it.
fn serialize_ctx(ctx: &SessionContext) -> Value {
    json!({
        "id": ctx.id.to_string(),
        "user_id": ctx.user_id,
        "round_id": ctx.round_id,
        "repo_uri": ctx.repo_uri,
        "scope_id": ctx.scope_id,
        "operation_type": ctx.operation.value(),
        "terraform_prv": ctx.terraform_prv.value(),
        "branch_name": ctx.branch_name,
        "iac_path": ctx.iac_path,
        "history": ctx.history.serialize(),
        "chat_history": ctx.chat_history.serialize(),
    })
}

fn deserialize_ctx(data: &Value) -> AppResult<SessionContext> {
    let field = |k: &str| data.get(k).ok_or_else(|| AppError::missing_key(k));
    let text = |k: &str| -> AppResult<String> {
        Ok(match field(k)? {
            Value::String(s) => s.clone(),
            other => pyfmt::str_value(other),
        })
    };
    let id = Uuid::parse_str(&text("id")?).map_err(|e| AppError::internal(e.to_string()))?;
    let operation = OperationType::from_value(&text("operation_type")?)
        .ok_or_else(|| AppError::internal("invalid operation_type in cached session context"))?;
    let provider = TerraformProvider::from_value(&text("terraform_prv")?)
        .ok_or_else(|| AppError::internal("invalid terraform_prv in cached session context"))?;
    let round_id = field("round_id")?
        .as_i64()
        .ok_or_else(|| AppError::internal("invalid round_id in cached session context"))?;
    let iac_path = match field("iac_path")? {
        Value::Null => None,
        Value::String(s) => Some(s.clone()),
        other => Some(pyfmt::str_value(other)),
    };
    Ok(SessionContext::new(
        id,
        text("user_id")?,
        round_id,
        text("repo_uri")?,
        text("scope_id")?,
        provider,
        text("branch_name")?,
        iac_path,
        operation,
        field("history")?,
        field("chat_history")?,
    ))
}

fn not_found(id: &Uuid) -> AppError {
    AppError::kind(ErrorKind::SessionTerminal, format!("Session {id} not found."), 404)
}

fn i4(v: i64) -> i32 {
    v as i32
}

fn enum_from_name<T>(raw: &str, parse: fn(&str) -> Option<T>) -> AppResult<T> {
    parse(raw).ok_or_else(|| AppError::internal(format!("unknown enum name '{raw}' in database")))
}

/// A `sessions` row.
#[derive(Debug, Clone)]
struct SessionRow {
    id: i64,
    uuid: Uuid,
    user_id: i64,
    operation: OperationType,
    in_flight: bool,
    is_blocked: bool,
    created_at: DateTime<Utc>,
    updated_at: DateTime<Utc>,
}

const SESSION_COLUMNS: &str = "sessions.id, sessions.uuid, sessions.user_id, sessions.operation::text AS operation, sessions.in_flight, sessions.is_blocked, sessions.created_at, sessions.updated_at";

fn session_row(row: &PgRow) -> AppResult<SessionRow> {
    Ok(SessionRow {
        id: i64::from(row.try_get::<i32, _>("id").map_err(db_error)?),
        uuid: row.try_get("uuid").map_err(db_error)?,
        user_id: i64::from(row.try_get::<i32, _>("user_id").map_err(db_error)?),
        operation: enum_from_name(
            &row.try_get::<String, _>("operation").map_err(db_error)?,
            OperationType::from_name,
        )?,
        in_flight: row.try_get("in_flight").map_err(db_error)?,
        is_blocked: row.try_get("is_blocked").map_err(db_error)?,
        created_at: row.try_get("created_at").map_err(db_error)?,
        updated_at: row.try_get("updated_at").map_err(db_error)?,
    })
}

const USER_COLUMNS: &str = "id, issuer, subject, email, display_name, operation_role::text AS operation_role, panel_role::text AS panel_role, created_at";

fn user_row(row: &PgRow) -> AppResult<User> {
    let panel: Option<String> = row.try_get("panel_role").map_err(db_error)?;
    Ok(User {
        id: i64::from(row.try_get::<i32, _>("id").map_err(db_error)?),
        issuer: row.try_get("issuer").map_err(db_error)?,
        subject: row.try_get("subject").map_err(db_error)?,
        email: row.try_get("email").map_err(db_error)?,
        display_name: row.try_get("display_name").map_err(db_error)?,
        operation_role: enum_from_name(
            &row.try_get::<String, _>("operation_role").map_err(db_error)?,
            OperationRole::from_name,
        )?,
        panel_role: match panel {
            Some(p) => Some(enum_from_name(&p, PanelRole::from_name)?),
            None => None,
        },
        created_at: row.try_get("created_at").map_err(db_error)?,
    })
}

/// Profile/role fields `update_user` may set; `None` leaves a field alone.
#[derive(Debug, Clone, Default)]
pub struct UserUpdate {
    pub email: Option<String>,
    pub display_name: Option<String>,
    pub operation_role: Option<OperationRole>,
    /// `Some(None)` clears the panel role.
    pub panel_role: Option<Option<PanelRole>>,
}

impl UserUpdate {
    pub fn is_empty(&self) -> bool {
        self.email.is_none()
            && self.display_name.is_none()
            && self.operation_role.is_none()
            && self.panel_role.is_none()
    }
}

/// Filters of the session listing endpoints.
#[derive(Debug, Clone, Default)]
pub struct SessionFilter {
    pub user_pk: Option<i64>,
    pub operation: Option<OperationType>,
    pub status: Option<SessionStatus>,
    pub search: Option<String>,
    pub user_email: Option<String>,
}

#[derive(Clone)]
pub struct DatabaseService {
    pool: PgPool,
    cache: RedisCache,
    storage: Arc<dyn ObjectStorage>,
    cfg: &'static SystemConfig,
}

impl DatabaseService {
    pub fn new(pool: PgPool, cache: RedisCache, storage: Arc<dyn ObjectStorage>, cfg: &'static SystemConfig) -> Self {
        Self {
            pool,
            cache,
            storage,
            cfg,
        }
    }

    pub fn pool(&self) -> &PgPool {
        &self.pool
    }

    // --- private reads -------------------------------------------------------

    /// session uuid -> integer pk. Write-once.
    async fn map_session_id(&self, uuid: &Uuid) -> AppResult<Option<i64>> {
        let pool = self.pool.clone();
        let id = *uuid;
        let v = self
            .cache
            .get_or_set(&k_sid(uuid), Ttl::Fixed(ttl(TTL_FACTS)), || async move {
                let row = sqlx::query("SELECT id FROM sessions WHERE uuid = $1")
                    .bind(id)
                    .fetch_optional(&pool)
                    .await
                    .map_err(db_error)?;
                Ok(match row {
                    Some(r) => Some(json!(r.try_get::<i32, _>("id").map_err(db_error)?)),
                    None => None,
                })
            })
            .await?;
        Ok(v.and_then(|v| v.as_i64()))
    }

    /// Not cached: the row carries mutable lock state that must be fresh.
    async fn load_session(&self, uuid: &Uuid) -> AppResult<Option<SessionRow>> {
        let row = sqlx::query(&format!("SELECT {SESSION_COLUMNS} FROM sessions WHERE uuid = $1"))
            .bind(uuid)
            .fetch_optional(&self.pool)
            .await
            .map_err(db_error)?;
        row.as_ref().map(session_row).transpose()
    }

    /// user pk -> display email for read models and tracing.
    async fn map_user_email(&self, pk: i64) -> AppResult<String> {
        let row = sqlx::query("SELECT email FROM users WHERE id = $1")
            .bind(i4(pk))
            .fetch_optional(&self.pool)
            .await
            .map_err(db_error)?;
        if let Some(r) = row {
            let email: Option<String> = r.try_get("email").map_err(db_error)?;
            if let Some(email) = email.filter(|e| !e.is_empty()) {
                return Ok(email);
            }
        }
        Ok(format!("user-{pk}"))
    }

    /// The single row of `table` for a session, or None (a missing session
    /// or a count other than one reads as absent, like `db.get_by`).
    async fn single_by_session(&self, sql: &str, sid: Option<i64>) -> AppResult<Option<PgRow>> {
        let Some(sid) = sid else {
            return Ok(None);
        };
        let rows = sqlx::query(sql)
            .bind(i4(sid))
            .fetch_all(&self.pool)
            .await
            .map_err(db_error)?;
        Ok(if rows.len() == 1 { rows.into_iter().next() } else { None })
    }

    async fn workspace_facts(&self, uuid: &Uuid) -> AppResult<Option<WorkspaceFacts>> {
        let this = self.clone();
        let id = *uuid;
        let data = self
            .cache
            .get_or_set(&k_workspace(uuid), Ttl::Fixed(ttl(TTL_FACTS)), || async move {
                let sid = this.map_session_id(&id).await?;
                let row = this
                    .single_by_session(
                        "SELECT uri, branch, root_path FROM workspaces WHERE session_id = $1",
                        sid,
                    )
                    .await?;
                Ok(match row {
                    None => None,
                    Some(r) => Some(json!({
                        "uri": r.try_get::<String, _>("uri").map_err(db_error)?,
                        "branch": r.try_get::<String, _>("branch").map_err(db_error)?,
                        "root_path": r.try_get::<Option<String>, _>("root_path").map_err(db_error)?,
                    })),
                })
            })
            .await?;
        match data {
            None => Ok(None),
            Some(d) => Ok(Some(
                serde_json::from_value(d).map_err(|e| AppError::internal(e.to_string()))?,
            )),
        }
    }

    async fn provider_facts(&self, uuid: &Uuid) -> AppResult<Option<ProviderFacts>> {
        let this = self.clone();
        let id = *uuid;
        let data = self
            .cache
            .get_or_set(&k_provider(uuid), Ttl::Fixed(ttl(TTL_FACTS)), || async move {
                let sid = this.map_session_id(&id).await?;
                let row = this
                    .single_by_session(
                        "SELECT provider::text AS provider, scope_id FROM terraform_providers WHERE session_id = $1",
                        sid,
                    )
                    .await?;
                Ok(match row {
                    None => None,
                    Some(r) => {
                        let provider = enum_from_name(
                            &r.try_get::<String, _>("provider").map_err(db_error)?,
                            TerraformProvider::from_name,
                        )?;
                        Some(json!({
                            "provider": provider.value(),
                            "scope_id": r.try_get::<String, _>("scope_id").map_err(db_error)?,
                        }))
                    }
                })
            })
            .await?;
        let Some(d) = data else {
            return Ok(None);
        };
        let provider = d
            .get("provider")
            .and_then(Value::as_str)
            .and_then(TerraformProvider::from_value)
            .ok_or_else(|| AppError::internal("invalid cached provider facts"))?;
        let scope_id = d
            .get("scope_id")
            .and_then(Value::as_str)
            .ok_or_else(|| AppError::missing_key("scope_id"))?
            .to_string();
        Ok(Some(ProviderFacts { provider, scope_id }))
    }

    async fn first_query(&self, uuid: &Uuid) -> AppResult<Option<String>> {
        let this = self.clone();
        let id = *uuid;
        let v = self
            .cache
            .get_or_set(&k_first_query(uuid), Ttl::Fixed(ttl(TTL_FACTS)), || async move {
                let sid = this.map_session_id(&id).await?;
                let row = this
                    .single_by_session("SELECT first_query FROM histories WHERE session_id = $1", sid)
                    .await?;
                Ok(match row {
                    Some(r) => Some(Value::String(r.try_get::<String, _>("first_query").map_err(db_error)?)),
                    None => None,
                })
            })
            .await?;
        Ok(v.map(|v| match v {
            Value::String(s) => s,
            other => pyfmt::str_value(&other),
        }))
    }

    /// Both conversation payloads travel together: reading only one would
    /// make the next `update_history` overwrite the other with an empty list.
    async fn history_payloads(&self, uuid: &Uuid) -> AppResult<Option<Value>> {
        let this = self.clone();
        let id = *uuid;
        self.cache
            .get_or_set(&k_history(uuid), Ttl::Fixed(ttl(TTL_HISTORY)), || async move {
                let sid = this.map_session_id(&id).await?;
                let row = this
                    .single_by_session(
                        "SELECT payload::text AS payload, chat_payload::text AS chat_payload FROM histories WHERE session_id = $1",
                        sid,
                    )
                    .await?;
                Ok(match row {
                    None => None,
                    Some(r) => Some(json!({
                        "payload": parse_json_column(&r, "payload")?,
                        "chat_payload": parse_json_column(&r, "chat_payload")?,
                    })),
                })
            })
            .await
    }

    async fn load_pull_requests(&self, sid: Option<i64>) -> AppResult<Value> {
        let Some(sid) = sid else {
            return Ok(Value::Array(Vec::new()));
        };
        let rows = sqlx::query(
            "SELECT pull_requests.provider::text AS provider, pull_requests.url, pull_requests.number \
             FROM pull_requests JOIN rounds ON pull_requests.round_id = rounds.id \
             WHERE rounds.session_id = $1 ORDER BY rounds.number, pull_requests.id",
        )
        .bind(i4(sid))
        .fetch_all(&self.pool)
        .await
        .map_err(db_error)?;
        let mut out = Vec::new();
        for r in rows {
            out.push(json!({
                "provider": r.try_get::<String, _>("provider").map_err(db_error)?,
                "url": r.try_get::<String, _>("url").map_err(db_error)?,
                "number": r.try_get::<i32, _>("number").map_err(db_error)?,
            }));
        }
        Ok(Value::Array(out))
    }

    /// Pk of the session's highest-numbered round.
    async fn latest_round_id(&self, sid: i64) -> AppResult<Option<i64>> {
        let row = sqlx::query("SELECT id FROM rounds WHERE session_id = $1 ORDER BY number DESC LIMIT 1")
            .bind(i4(sid))
            .fetch_optional(&self.pool)
            .await
            .map_err(db_error)?;
        Ok(match row {
            Some(r) => Some(i64::from(r.try_get::<i32, _>("id").map_err(db_error)?)),
            None => None,
        })
    }

    async fn pull_requests(&self, uuid: &Uuid) -> AppResult<Vec<Value>> {
        let this = self.clone();
        let id = *uuid;
        let data = self
            .cache
            .get_or_set(&k_pull_requests(uuid), Ttl::Fixed(ttl(TTL_PR)), || async move {
                let sid = this.map_session_id(&id).await?;
                Ok(Some(this.load_pull_requests(sid).await?))
            })
            .await?;
        Ok(match data {
            Some(Value::Array(items)) => items,
            _ => Vec::new(),
        })
    }

    async fn insert_returning_id(&self, mut qb: QueryBuilder<'_, Postgres>) -> AppResult<i64> {
        qb.push(" RETURNING id");
        let mut tx = self.pool.begin().await.map_err(db_error)?;
        let row = qb.build().fetch_one(&mut *tx).await.map_err(db_error)?;
        tx.commit().await.map_err(db_error)?;
        Ok(i64::from(row.try_get::<i32, _>("id").map_err(db_error)?))
    }

    async fn create_status(
        &self,
        uuid: &Uuid,
        status: SessionStatus,
        msg: &str,
        round_id: Option<i64>,
    ) -> AppResult<i64> {
        let Some(sid) = self.map_session_id(uuid).await? else {
            return Err(not_found(uuid));
        };
        let round_id = match round_id.filter(|r| *r != 0) {
            Some(r) => Some(r),
            None => self.latest_round_id(sid).await?,
        };
        let Some(round_id) = round_id.filter(|r| *r != 0) else {
            return Err(AppError::kind(
                ErrorKind::SessionConflict,
                format!("Session {uuid} has no rounds; cannot record a status."),
                409,
            ));
        };
        let now = now_micros();
        let mut qb = QueryBuilder::new(
            "INSERT INTO statuses (session_id, round_id, status, message, created_at, updated_at) VALUES (",
        );
        qb.push_bind(i4(sid))
            .push(", ")
            .push_bind(i4(round_id))
            .push(", ")
            .push_bind(status.name())
            .push("::sessionstatus, ")
            .push_bind(msg.to_string())
            .push(", ")
            .push_bind(now)
            .push(", ")
            .push_bind(now)
            .push(")");
        self.insert_returning_id(qb).await
    }

    // --- users -------------------------------------------------------------------

    pub async fn get_user(&self, user_id: i64) -> AppResult<Option<User>> {
        let row = sqlx::query(&format!("SELECT {USER_COLUMNS} FROM users WHERE id = $1"))
            .bind(i4(user_id))
            .fetch_optional(&self.pool)
            .await
            .map_err(db_error)?;
        row.as_ref().map(user_row).transpose()
    }

    pub async fn get_user_by_identity(&self, issuer: &str, subject: &str) -> AppResult<Option<User>> {
        let row = sqlx::query(&format!(
            "SELECT {USER_COLUMNS} FROM users WHERE issuer = $1 AND subject = $2"
        ))
        .bind(issuer)
        .bind(subject)
        .fetch_optional(&self.pool)
        .await
        .map_err(db_error)?;
        row.as_ref().map(user_row).transpose()
    }

    pub async fn create_user(
        &self,
        issuer: &str,
        subject: &str,
        email: Option<&str>,
        display_name: Option<&str>,
        operation_role: OperationRole,
        panel_role: Option<PanelRole>,
    ) -> AppResult<User> {
        let now = now_micros();
        let mut tx = self.pool.begin().await.map_err(db_error)?;
        let row = sqlx::query(&format!(
            "INSERT INTO users (issuer, subject, email, display_name, operation_role, panel_role, created_at, updated_at) \
             VALUES ($1, $2, $3, $4, $5::operationrole, $6::panelrole, $7, $8) RETURNING {USER_COLUMNS}"
        ))
        .bind(issuer)
        .bind(subject)
        .bind(email)
        .bind(display_name)
        .bind(operation_role.name())
        .bind(panel_role.map(|p| p.name()))
        .bind(now)
        .bind(now)
        .fetch_one(&mut *tx)
        .await;
        let row = match row {
            Ok(r) => r,
            Err(e) if is_unique_violation(&e) => {
                return Err(AppError::kind(
                    ErrorKind::UserAlreadyExists,
                    format!("User {issuer}/{subject} already exists"),
                    409,
                ));
            }
            Err(e) => return Err(db_error(e)),
        };
        tx.commit().await.map_err(db_error)?;
        user_row(&row)
    }

    pub async fn update_user(&self, user_id: i64, values: &UserUpdate) -> AppResult<User> {
        let mut qb: QueryBuilder<Postgres> = QueryBuilder::new("UPDATE users SET ");
        {
            let mut sep = qb.separated(", ");
            if let Some(email) = &values.email {
                sep.push("email = ").push_bind_unseparated(email.clone());
            }
            if let Some(name) = &values.display_name {
                sep.push("display_name = ").push_bind_unseparated(name.clone());
            }
            if let Some(role) = values.operation_role {
                sep.push("operation_role = ")
                    .push_bind_unseparated(role.name())
                    .push_unseparated("::operationrole");
            }
            if let Some(panel) = values.panel_role {
                sep.push("panel_role = ")
                    .push_bind_unseparated(panel.map(|p| p.name()))
                    .push_unseparated("::panelrole");
            }
            sep.push("updated_at = ").push_bind_unseparated(now_micros());
        }
        qb.push(" WHERE id = ").push_bind(i4(user_id));
        let mut tx = self.pool.begin().await.map_err(db_error)?;
        let res = qb.build().execute(&mut *tx).await.map_err(db_error)?;
        if res.rows_affected() != 1 {
            return Err(AppError::kind(
                ErrorKind::UserNotFound,
                format!("User {user_id} not found"),
                404,
            ));
        }
        tx.commit().await.map_err(db_error)?;
        self.get_user(user_id)
            .await?
            .ok_or_else(|| AppError::kind(ErrorKind::UserNotFound, format!("User {user_id} not found"), 404))
    }

    pub async fn list_users(&self, offset: i64, limit: i64, search: Option<&str>) -> AppResult<(Vec<User>, i64)> {
        let push_filter = |qb: &mut QueryBuilder<Postgres>| {
            if let Some(s) = search.filter(|s| !s.is_empty()) {
                let pattern = format!("%{s}%");
                qb.push(" WHERE (users.email ILIKE ")
                    .push_bind(pattern.clone())
                    .push(" OR users.display_name ILIKE ")
                    .push_bind(pattern)
                    .push(")");
            }
        };
        let mut count_qb: QueryBuilder<Postgres> = QueryBuilder::new("SELECT count(*) AS n FROM users");
        push_filter(&mut count_qb);
        let count: i64 = count_qb
            .build()
            .fetch_one(&self.pool)
            .await
            .map_err(db_error)?
            .try_get("n")
            .map_err(db_error)?;
        let mut qb: QueryBuilder<Postgres> = QueryBuilder::new(format!("SELECT {USER_COLUMNS} FROM users"));
        push_filter(&mut qb);
        qb.push(" ORDER BY users.created_at DESC OFFSET ")
            .push_bind(offset)
            .push(" LIMIT ")
            .push_bind(limit);
        let rows = qb.build().fetch_all(&self.pool).await.map_err(db_error)?;
        let users = rows.iter().map(user_row).collect::<AppResult<Vec<_>>>()?;
        Ok((users, count))
    }

    /// Emails of users whose panel role is `minimum` or higher; users
    /// without an email are skipped (nowhere to notify).
    pub async fn list_emails_with_panel_role(&self, minimum: PanelRole) -> AppResult<Vec<String>> {
        let roles: Vec<&str> = PanelRole::ALL
            .iter()
            .filter(|r| r.at_least(minimum))
            .map(|r| r.name())
            .collect();
        let rows = sqlx::query("SELECT email FROM users WHERE panel_role::text = ANY($1) AND email IS NOT NULL")
            .bind(&roles)
            .fetch_all(&self.pool)
            .await
            .map_err(db_error)?;
        let mut out = Vec::new();
        for r in rows {
            let email: Option<String> = r.try_get("email").map_err(db_error)?;
            if let Some(e) = email.filter(|e| !e.is_empty()) {
                out.push(e);
            }
        }
        Ok(out)
    }

    // --- sessions ------------------------------------------------------------------

    /// Owning user pk for a session. Write-once.
    pub async fn get_session_owner(&self, uuid: &Uuid) -> AppResult<i64> {
        let pool = self.pool.clone();
        let id = *uuid;
        let owner = self
            .cache
            .get_or_set(&k_owner(uuid), Ttl::Fixed(ttl(TTL_FACTS)), || async move {
                let row = sqlx::query("SELECT user_id FROM sessions WHERE uuid = $1")
                    .bind(id)
                    .fetch_optional(&pool)
                    .await
                    .map_err(db_error)?;
                Ok(match row {
                    Some(r) => Some(json!(r.try_get::<i32, _>("user_id").map_err(db_error)?)),
                    None => None,
                })
            })
            .await?;
        owner.and_then(|v| v.as_i64()).ok_or_else(|| not_found(uuid))
    }

    #[allow(clippy::too_many_arguments)]
    pub async fn create_session(
        &self,
        session_id: &Uuid,
        user_pk: i64,
        operation: OperationType,
        repo_uri: &str,
        terraform_prv: TerraformProvider,
        scope_id: &str,
        branch_name: &str,
        query: &str,
        iac_path: Option<&str>,
    ) -> AppResult<i64> {
        let now = now_micros();
        let mut qb = QueryBuilder::new(
            "INSERT INTO sessions (uuid, user_id, operation, in_flight, is_blocked, created_at, updated_at) VALUES (",
        );
        qb.push_bind(*session_id)
            .push(", ")
            .push_bind(i4(user_pk))
            .push(", ")
            .push_bind(operation.name())
            .push("::operationtype, false, false, ")
            .push_bind(now)
            .push(", ")
            .push_bind(now)
            .push(")");
        let sid = self.insert_returning_id(qb).await?;

        let now = now_micros();
        let mut qb = QueryBuilder::new(
            "INSERT INTO workspaces (session_id, uri, branch, root_path, created_at, updated_at) VALUES (",
        );
        qb.push_bind(i4(sid))
            .push(", ")
            .push_bind(repo_uri.to_string())
            .push(", ")
            .push_bind(branch_name.to_string())
            .push(", ")
            .push_bind(iac_path.map(str::to_string))
            .push(", ")
            .push_bind(now)
            .push(", ")
            .push_bind(now)
            .push(")");
        self.insert_returning_id(qb).await?;

        let now = now_micros();
        let mut qb = QueryBuilder::new(
            "INSERT INTO terraform_providers (session_id, provider, scope_id, created_at, updated_at) VALUES (",
        );
        qb.push_bind(i4(sid))
            .push(", ")
            .push_bind(terraform_prv.name())
            .push("::terraformprovider, ")
            .push_bind(scope_id.to_string())
            .push(", ")
            .push_bind(now)
            .push(", ")
            .push_bind(now)
            .push(")");
        self.insert_returning_id(qb).await?;

        let now = now_micros();
        let mut qb = QueryBuilder::new(
            "INSERT INTO histories (session_id, first_query, payload, chat_payload, created_at, updated_at) VALUES (",
        );
        qb.push_bind(i4(sid))
            .push(", ")
            .push_bind(query.to_string())
            .push(", '[]'::json, '[]'::json, ")
            .push_bind(now)
            .push(", ")
            .push_bind(now)
            .push(")");
        self.insert_returning_id(qb).await?;

        let round_id = self.create_round(session_id, query).await?;
        self.create_status(
            session_id,
            SessionStatus::Started,
            "Preparing your workspace…",
            Some(round_id),
        )
        .await?;

        self.cache
            .set_json_many(&[
                (k_sid(session_id), json!(sid), Some(ttl(TTL_FACTS))),
                (k_owner(session_id), json!(user_pk), Some(ttl(TTL_FACTS))),
                (
                    k_workspace(session_id),
                    json!({"uri": repo_uri, "branch": branch_name, "root_path": iac_path}),
                    Some(ttl(TTL_FACTS)),
                ),
                (
                    k_provider(session_id),
                    json!({"provider": terraform_prv.value(), "scope_id": scope_id}),
                    Some(ttl(TTL_FACTS)),
                ),
                (k_first_query(session_id), json!(query), Some(ttl(TTL_FACTS))),
            ])
            .await;
        Ok(sid)
    }

    pub async fn get_session_context(&self, uuid: &Uuid) -> AppResult<SessionContext> {
        let this = self.clone();
        let id = *uuid;
        let data = self
            .cache
            .get_or_set(&k_context(uuid), Ttl::Fixed(ttl(TTL_CONTEXT)), || async move {
                let Some(session) = this.load_session(&id).await? else {
                    return Err(not_found(&id));
                };
                let (username, workspace, provider, history, round_id) = futures::join!(
                    this.map_user_email(session.user_id),
                    this.workspace_facts(&id),
                    this.provider_facts(&id),
                    this.history_payloads(&id),
                    this.latest_round_id(session.id),
                );
                let (username, workspace, provider, history, round_id) =
                    (username?, workspace?, provider?, history?, round_id?);
                let Some(workspace) = workspace else {
                    return Err(AppError::kind(
                        ErrorKind::SessionTerminal,
                        format!("Session {id} does not have a workspace"),
                        404,
                    ));
                };
                let Some(provider) = provider else {
                    return Err(AppError::kind(
                        ErrorKind::SessionTerminal,
                        format!("Session {id} does not have an associated cloud provider"),
                        404,
                    ));
                };
                let Some(round_id) = round_id else {
                    return Err(AppError::kind(
                        ErrorKind::SessionConflict,
                        format!("Session {id} does not have an associated round."),
                        409,
                    ));
                };
                let Some(history) = history else {
                    return Err(AppError::kind(
                        ErrorKind::SessionConflict,
                        format!("Session {id} does not have an associated history."),
                        409,
                    ));
                };
                let ctx = SessionContext::new(
                    session.uuid,
                    username,
                    round_id,
                    workspace.uri,
                    provider.scope_id,
                    provider.provider,
                    workspace.branch,
                    workspace.root_path,
                    session.operation,
                    history.get("payload").unwrap_or(&Value::Null),
                    history.get("chat_payload").unwrap_or(&Value::Null),
                );
                Ok(Some(serialize_ctx(&ctx)))
            })
            .await?;
        deserialize_ctx(&data.unwrap_or(Value::Null))
    }

    /// Latest recorded status, STARTED when none has been written yet.
    async fn current_status(&self, uuid: &Uuid) -> AppResult<SessionStatus> {
        match self.get_last_status(uuid).await {
            Ok(s) => Ok(s.status),
            Err(e) if e.is(ErrorKind::LastStatus) => Ok(SessionStatus::Started),
            Err(e) => Err(e),
        }
    }

    async fn construct_summary(&self, s: &SessionRow) -> AppResult<SessionSummary> {
        let (workspace, provider, username, first_query, current_status) = futures::join!(
            self.workspace_facts(&s.uuid),
            self.provider_facts(&s.uuid),
            self.map_user_email(s.user_id),
            self.first_query(&s.uuid),
            self.current_status(&s.uuid),
        );
        let (workspace, provider, username, first_query, current_status) =
            (workspace?, provider?, username?, first_query?, current_status?);
        let (Some(workspace), Some(provider)) = (workspace, provider) else {
            return Err(AppError::kind(
                ErrorKind::SessionTerminal,
                format!("Session {} is misconfigured", s.uuid),
                500,
            ));
        };
        Ok(SessionSummary {
            uuid: s.uuid,
            username: Some(username),
            operation: s.operation,
            provider: provider.provider,
            first_query,
            workspace: WorkspaceRef {
                uri: workspace.uri,
                branch: workspace.branch,
                root_path: workspace.root_path,
            },
            current_status,
            in_flight: s.in_flight,
            is_blocked: s.is_blocked,
            created_at: s.created_at,
            updated_at: s.updated_at,
        })
    }

    pub async fn get_session_summary(&self, uuid: &Uuid) -> AppResult<SessionSummary> {
        let Some(s) = self.load_session(uuid).await? else {
            return Err(not_found(uuid));
        };
        self.construct_summary(&s).await
    }

    /// Paginated summaries. `user_pk` None lists across all users (admin);
    /// `user_email` optionally filters that listing by owner email.
    pub async fn list_sessions(
        &self,
        filter: &SessionFilter,
        offset: i64,
        limit: i64,
    ) -> AppResult<PaginatedSessionSummary> {
        let build = |qb: &mut QueryBuilder<Postgres>| {
            if filter.user_email.as_deref().is_some_and(|e| !e.is_empty()) {
                qb.push(" JOIN users ON users.id = sessions.user_id");
            }
            let search = filter.search.as_deref().filter(|s| !s.is_empty());
            if search.is_some() {
                qb.push(" JOIN histories ON histories.session_id = sessions.id JOIN workspaces ON workspaces.session_id = sessions.id");
            }
            if filter.status.is_some() {
                qb.push(
                    " JOIN (SELECT statuses.session_id AS session_id, max(statuses.id) AS last_id FROM statuses GROUP BY statuses.session_id) AS latest \
                     ON latest.session_id = sessions.id JOIN statuses ON statuses.id = latest.last_id",
                );
            }
            qb.push(" WHERE true");
            if let Some(pk) = filter.user_pk {
                qb.push(" AND sessions.user_id = ").push_bind(i4(pk));
            }
            if let Some(email) = filter.user_email.as_deref().filter(|e| !e.is_empty()) {
                qb.push(" AND users.email ILIKE ").push_bind(format!("%{email}%"));
            }
            if let Some(op) = filter.operation {
                qb.push(" AND sessions.operation = ")
                    .push_bind(op.name())
                    .push("::operationtype");
            }
            if let Some(s) = search {
                let pattern = format!("%{s}%");
                qb.push(" AND (histories.first_query ILIKE ")
                    .push_bind(pattern.clone())
                    .push(" OR workspaces.uri ILIKE ")
                    .push_bind(pattern.clone())
                    .push(" OR CAST(sessions.uuid AS VARCHAR) ILIKE ")
                    .push_bind(pattern)
                    .push(")");
            }
            if let Some(status) = filter.status {
                qb.push(" AND statuses.status = ")
                    .push_bind(status.name())
                    .push("::sessionstatus");
            }
        };
        let mut count_qb: QueryBuilder<Postgres> =
            QueryBuilder::new("SELECT count(*) AS n FROM (SELECT sessions.id FROM sessions");
        build(&mut count_qb);
        count_qb.push(") AS anon_1");
        let count: i64 = count_qb
            .build()
            .fetch_one(&self.pool)
            .await
            .map_err(db_error)?
            .try_get("n")
            .map_err(db_error)?;

        let mut qb: QueryBuilder<Postgres> = QueryBuilder::new(format!("SELECT {SESSION_COLUMNS} FROM sessions"));
        build(&mut qb);
        qb.push(" ORDER BY sessions.created_at DESC OFFSET ")
            .push_bind(offset)
            .push(" LIMIT ")
            .push_bind(limit);
        let rows = qb.build().fetch_all(&self.pool).await.map_err(db_error)?;
        let sessions = rows.iter().map(session_row).collect::<AppResult<Vec<_>>>()?;

        // Summaries only touch the cache / point reads: build the page concurrently.
        let summaries = futures::future::join_all(sessions.iter().map(|s| self.construct_summary(s)))
            .await
            .into_iter()
            .collect::<AppResult<Vec<_>>>()?;

        Ok(PaginatedSessionSummary {
            items: summaries,
            total: count,
            page: offset / limit + 1,
            page_size: limit,
            total_pages: if count > 0 { (count + limit - 1) / limit } else { 0 },
        })
    }

    // --- session detail aggregate ----------------------------------------------------

    async fn artifact_url(&self, uri: &str) -> AppResult<String> {
        self.storage.presigned_get_url(uri, None).await
    }

    /// Full session aggregate: facts, timeline, and per-round artifacts.
    ///
    /// Live sessions are always read fresh; finished sessions can never
    /// change again, so those are served from a cached copy. Either history
    /// variant is always read fresh. Always returns the admin superset.
    pub async fn get_session_detail(
        &self,
        uuid: &Uuid,
        include_chat_history: bool,
        include_history: bool,
    ) -> AppResult<AdminSessionDetail> {
        let fresh = include_chat_history || include_history;
        if !fresh && let Some(cached) = self.cache.get_json(&k_detail(uuid)).await {
            match serde_json::from_value::<AdminSessionDetail>(cached) {
                Ok(d) => return Ok(d),
                Err(e) => {
                    tracing::warn!(
                        "Stale-shaped cache entry at {} failed to validate ({e}); dropping it",
                        k_detail(uuid)
                    );
                    self.cache.invalidate(&[&k_detail(uuid)]).await;
                }
            }
        }

        let Some(s) = self.load_session(uuid).await? else {
            return Err(not_found(uuid));
        };
        let sid = i4(s.id);
        let workspace = sqlx::query("SELECT uri, branch, root_path FROM workspaces WHERE session_id = $1 ORDER BY id")
            .bind(sid)
            .fetch_all(&self.pool)
            .await
            .map_err(db_error)?;
        let providers = sqlx::query(
            "SELECT provider::text AS provider, scope_id FROM terraform_providers WHERE session_id = $1 ORDER BY id",
        )
        .bind(sid)
        .fetch_all(&self.pool)
        .await
        .map_err(db_error)?;
        let histories = sqlx::query(
            "SELECT first_query, payload::text AS payload, chat_payload::text AS chat_payload FROM histories WHERE session_id = $1 ORDER BY id",
        )
        .bind(sid)
        .fetch_all(&self.pool)
        .await
        .map_err(db_error)?;
        if workspace.is_empty() || providers.is_empty() {
            return Err(AppError::kind(
                ErrorKind::SessionTerminal,
                format!("Session {uuid} is missconfigured"),
                500,
            ));
        }
        let ws = &workspace[0];
        let pv = &providers[0];
        let history = histories.first();

        // max(id) is the append-order proxy for "latest".
        let current =
            sqlx::query("SELECT status::text AS status FROM statuses WHERE session_id = $1 ORDER BY id DESC LIMIT 1")
                .bind(sid)
                .fetch_optional(&self.pool)
                .await
                .map_err(db_error)?;
        let current_status = match current {
            Some(r) => enum_from_name(
                &r.try_get::<String, _>("status").map_err(db_error)?,
                SessionStatus::from_name,
            )?,
            None => SessionStatus::Started,
        };

        let rounds = self.round_details(sid).await?;

        let detail = AdminSessionDetail {
            uuid: s.uuid,
            username: Some(self.map_user_email(s.user_id).await?),
            operation: s.operation,
            provider: enum_from_name(
                &pv.try_get::<String, _>("provider").map_err(db_error)?,
                TerraformProvider::from_name,
            )?,
            first_query: match history {
                Some(h) => Some(h.try_get::<String, _>("first_query").map_err(db_error)?),
                None => None,
            },
            workspace: WorkspaceRef {
                uri: ws.try_get("uri").map_err(db_error)?,
                branch: ws.try_get("branch").map_err(db_error)?,
                root_path: ws.try_get("root_path").map_err(db_error)?,
            },
            current_status,
            in_flight: s.in_flight,
            is_blocked: s.is_blocked,
            created_at: s.created_at,
            updated_at: s.updated_at,
            scope_id: pv.try_get("scope_id").map_err(db_error)?,
            rounds,
            chat_history: match (include_chat_history, history) {
                (true, Some(h)) => Some(parse_json_column(h, "chat_payload")?),
                _ => None,
            },
            history: match (include_history, history) {
                (true, Some(h)) => Some(parse_json_column(h, "payload")?),
                _ => None,
            },
        };

        if !fresh && TERMINAL.contains(&detail.current_status) && !detail.in_flight {
            let value = serde_json::to_value(&detail).map_err(|e| AppError::internal(e.to_string()))?;
            self.cache
                .set_json(&k_detail(uuid), &value, Some(ttl(TTL_DETAIL)))
                .await;
        }
        Ok(detail)
    }

    async fn round_details(&self, sid: i32) -> AppResult<Vec<RoundDetail>> {
        let rounds =
            sqlx::query("SELECT id, number, query, created_at FROM rounds WHERE session_id = $1 ORDER BY number, id")
                .bind(sid)
                .fetch_all(&self.pool)
                .await
                .map_err(db_error)?;
        let round_ids: Vec<i32> = rounds
            .iter()
            .map(|r| r.try_get::<i32, _>("id"))
            .collect::<Result<_, _>>()
            .map_err(db_error)?;

        let statuses = sqlx::query(
            "SELECT round_id, status::text AS status, message, created_at, id FROM statuses WHERE round_id = ANY($1) ORDER BY created_at, id",
        )
        .bind(&round_ids)
        .fetch_all(&self.pool)
        .await
        .map_err(db_error)?;
        let prs = sqlx::query(
            "SELECT round_id, provider::text AS provider, url, number FROM pull_requests WHERE round_id = ANY($1) ORDER BY created_at, id",
        )
        .bind(&round_ids)
        .fetch_all(&self.pool)
        .await
        .map_err(db_error)?;
        let artifact_join = |table: &str, extra: &str| {
            format!(
                "SELECT t.round_id, t.id, t.created_at, a.uri, a.content_type, a.file_size_bytes{extra} \
                 FROM {table} t JOIN artifacts a ON a.id = t.artifact_id WHERE t.round_id = ANY($1) ORDER BY t.created_at, t.id"
            )
        };
        let reports = sqlx::query(&artifact_join("reports", ", t.type::text AS report_type"))
            .bind(&round_ids)
            .fetch_all(&self.pool)
            .await
            .map_err(db_error)?;
        let checks = sqlx::query(&artifact_join("compliance_checks", ", t.passed"))
            .bind(&round_ids)
            .fetch_all(&self.pool)
            .await
            .map_err(db_error)?;
        let plans = sqlx::query(&artifact_join("terraform_plans", ", t.targets"))
            .bind(&round_ids)
            .fetch_all(&self.pool)
            .await
            .map_err(db_error)?;
        let changes = sqlx::query(&artifact_join("code_changes", ", t.file_name"))
            .bind(&round_ids)
            .fetch_all(&self.pool)
            .await
            .map_err(db_error)?;

        let mut out = Vec::new();
        for r in &rounds {
            let rid: i32 = r.try_get("id").map_err(db_error)?;
            let mut status_entries = Vec::new();
            for st in rows_of_round(&statuses, rid)? {
                let message: String = st.try_get("message").map_err(db_error)?;
                status_entries.push(StatusEntry {
                    status: enum_from_name(
                        &st.try_get::<String, _>("status").map_err(db_error)?,
                        SessionStatus::from_name,
                    )?,
                    message: if message.is_empty() { None } else { Some(message) },
                    created_at: st.try_get("created_at").map_err(db_error)?,
                });
            }
            let mut report_refs = Vec::new();
            for row in rows_of_round(&reports, rid)? {
                let (id, url, content_type, size, created_at) = self.artifact_fields(row).await?;
                report_refs.push(ReportRef {
                    id,
                    url,
                    content_type,
                    file_size_bytes: size,
                    created_at,
                    report_type: enum_from_name(
                        &row.try_get::<String, _>("report_type").map_err(db_error)?,
                        ReportType::from_name,
                    )?,
                });
            }
            let mut check_refs = Vec::new();
            for row in rows_of_round(&checks, rid)? {
                let (id, url, content_type, size, created_at) = self.artifact_fields(row).await?;
                check_refs.push(ComplianceCheckRef {
                    id,
                    url,
                    content_type,
                    file_size_bytes: size,
                    created_at,
                    passed: row.try_get("passed").map_err(db_error)?,
                });
            }
            let mut plan_refs = Vec::new();
            for row in rows_of_round(&plans, rid)? {
                let (id, url, content_type, size, created_at) = self.artifact_fields(row).await?;
                plan_refs.push(TerraformPlanRef {
                    id,
                    url,
                    content_type,
                    file_size_bytes: size,
                    created_at,
                    targets: row.try_get("targets").map_err(db_error)?,
                });
            }
            let mut change_refs = Vec::new();
            for row in rows_of_round(&changes, rid)? {
                let (id, url, content_type, size, created_at) = self.artifact_fields(row).await?;
                change_refs.push(CodeChangeRef {
                    id,
                    url,
                    content_type,
                    file_size_bytes: size,
                    created_at,
                    file_name: row.try_get("file_name").map_err(db_error)?,
                });
            }
            let mut pr_refs = Vec::new();
            for row in rows_of_round(&prs, rid)? {
                pr_refs.push(PullRequestRef {
                    provider: row.try_get("provider").map_err(db_error)?,
                    url: row.try_get("url").map_err(db_error)?,
                    number: i64::from(row.try_get::<i32, _>("number").map_err(db_error)?),
                });
            }
            out.push(RoundDetail {
                id: i64::from(rid),
                number: i64::from(r.try_get::<i32, _>("number").map_err(db_error)?),
                query: r.try_get("query").map_err(db_error)?,
                statuses: status_entries,
                reports: report_refs,
                compliance_checks: check_refs,
                plans: plan_refs,
                code_changes: change_refs,
                pull_requests: pr_refs,
                created_at: r.try_get("created_at").map_err(db_error)?,
            });
        }
        Ok(out)
    }

    async fn artifact_fields(
        &self,
        row: &PgRow,
    ) -> AppResult<(i64, String, Option<String>, Option<i64>, DateTime<Utc>)> {
        let uri: String = row.try_get("uri").map_err(db_error)?;
        Ok((
            i64::from(row.try_get::<i32, _>("id").map_err(db_error)?),
            self.artifact_url(&uri).await?,
            row.try_get("content_type").map_err(db_error)?,
            row.try_get::<Option<i32>, _>("file_size_bytes")
                .map_err(db_error)?
                .map(i64::from),
            row.try_get("created_at").map_err(db_error)?,
        ))
    }

    pub async fn update_history(&self, ctx: &SessionContext) -> AppResult<()> {
        let fail = || {
            AppError::kind(
                ErrorKind::SessionConflict,
                format!("Failed to update history on session {}.", ctx.id),
                500,
            )
        };
        let Some(sid) = self.map_session_id(&ctx.id).await? else {
            return Err(fail());
        };
        let payload = ctx.history.serialize();
        let chat_payload = ctx.chat_history.serialize();
        let mut tx = self.pool.begin().await.map_err(db_error)?;
        let res = sqlx::query(
            "UPDATE histories SET payload = $1::json, chat_payload = $2::json, updated_at = $3 WHERE session_id = $4",
        )
        .bind(pyfmt::json_dumps(&payload))
        .bind(pyfmt::json_dumps(&chat_payload))
        .bind(now_micros())
        .bind(i4(sid))
        .execute(&mut *tx)
        .await
        .map_err(db_error)?;
        if res.rows_affected() != 1 {
            return Err(fail());
        }
        tx.commit().await.map_err(db_error)?;
        self.cache
            .set_json_many(&[
                (k_context(&ctx.id), serialize_ctx(ctx), Some(ttl(TTL_CONTEXT))),
                (
                    k_history(&ctx.id),
                    json!({"payload": payload, "chat_payload": chat_payload}),
                    Some(ttl(TTL_HISTORY)),
                ),
            ])
            .await;
        self.cache.invalidate(&[&k_detail(&ctx.id)]).await;
        Ok(())
    }

    /// Compare-and-set the in-flight lock, refusing finished sessions: one
    /// atomic UPDATE is both the CAS and the terminal guard, so two runners
    /// can never both win and a finished session can never be resumed.
    pub async fn acquire_in_flight(&self, uuid: &Uuid) -> AppResult<()> {
        let terminal: Vec<&str> = TERMINAL.iter().map(|s| s.name()).collect();
        let last_status = "(SELECT statuses.status FROM statuses WHERE statuses.session_id = sessions.id ORDER BY statuses.id DESC LIMIT 1)";
        let mut tx = self.pool.begin().await.map_err(db_error)?;
        let res = sqlx::query(&format!(
            "UPDATE sessions SET in_flight = true, updated_at = $1 WHERE sessions.uuid = $2 AND sessions.in_flight IS false \
             AND ({last_status} IS NULL OR {last_status}::text <> ALL($3))"
        ))
        .bind(now_micros())
        .bind(uuid)
        .bind(&terminal)
        .execute(&mut *tx)
        .await
        .map_err(db_error)?;
        tx.commit().await.map_err(db_error)?;
        if res.rows_affected() == 1 {
            return Ok(());
        }
        // Lost the CAS: reload once to report precisely why.
        if self.load_session(uuid).await?.is_none() {
            return Err(not_found(uuid));
        }
        if TERMINAL.contains(&self.current_status(uuid).await?) {
            return Err(AppError::kind(
                ErrorKind::SessionTerminal,
                format!("Session {uuid} is finished and cannot be resumed."),
                409,
            ));
        }
        Err(AppError::kind(
            ErrorKind::SessionConflict,
            format!("Session {uuid} already has an operation in flight."),
            409,
        ))
    }

    pub async fn release_in_flight(&self, uuid: &Uuid) -> AppResult<()> {
        let mut tx = self.pool.begin().await.map_err(db_error)?;
        let res = sqlx::query("UPDATE sessions SET in_flight = false, updated_at = $1 WHERE sessions.uuid = $2")
            .bind(now_micros())
            .bind(uuid)
            .execute(&mut *tx)
            .await
            .map_err(db_error)?;
        if res.rows_affected() != 1 {
            return Err(AppError::kind(
                ErrorKind::SessionConflict,
                format!("Failed to release in-flight lock on session {uuid}."),
                500,
            ));
        }
        tx.commit().await.map_err(db_error)?;
        Ok(())
    }

    /// Append a status row on the session's latest round (or `round_id`).
    pub async fn mark_session_status(
        &self,
        uuid: &Uuid,
        status: SessionStatus,
        msg: &str,
        round_id: Option<i64>,
    ) -> AppResult<()> {
        self.create_status(uuid, status, msg, round_id).await?;
        self.cache
            .set_json(
                &k_last_status(uuid),
                &json!({"status": status.value(), "message": msg}),
                Some(status_ttl(status)),
            )
            .await;
        // A no-op for live sessions, which are never cached.
        self.cache.invalidate(&[&k_detail(uuid)]).await;
        Ok(())
    }

    pub async fn get_last_status(&self, uuid: &Uuid) -> AppResult<Status> {
        let this = self.clone();
        let id = *uuid;
        let ttl_of = |loaded: &Value| -> u64 {
            loaded
                .get("status")
                .and_then(Value::as_str)
                .and_then(SessionStatus::from_value)
                .map(status_ttl)
                .unwrap_or_else(|| ttl(TTL_STATUS))
        };
        let data = self
            .cache
            .get_or_set(&k_last_status(uuid), Ttl::From(&ttl_of), || async move {
                let Some(sid) = this.map_session_id(&id).await?.filter(|s| *s != 0) else {
                    return Ok(None);
                };
                let row = sqlx::query(
                    "SELECT status::text AS status, message FROM statuses WHERE session_id = $1 ORDER BY id DESC LIMIT 1",
                )
                .bind(i4(sid))
                .fetch_optional(&this.pool)
                .await
                .map_err(db_error)?;
                Ok(match row {
                    None => None,
                    Some(r) => {
                        let status = enum_from_name(&r.try_get::<String, _>("status").map_err(db_error)?, SessionStatus::from_name)?;
                        Some(json!({"status": status.value(), "message": r.try_get::<String, _>("message").map_err(db_error)?}))
                    }
                })
            })
            .await?;
        let Some(data) = data else {
            return Err(AppError::kind(
                ErrorKind::LastStatus,
                format!("No status records for session {uuid}"),
                500,
            ));
        };
        let status = data
            .get("status")
            .and_then(Value::as_str)
            .and_then(SessionStatus::from_value)
            .ok_or_else(|| AppError::internal("invalid cached status"))?;
        let msg = match data.get("message") {
            Some(Value::String(s)) => s.clone(),
            Some(Value::Null) | None => String::new(),
            Some(other) => pyfmt::str_value(other),
        };
        Ok(Status { status, msg })
    }

    pub async fn mark_failed(&self, uuid: &Uuid, msg: &str) -> AppResult<()> {
        self.mark_session_status(uuid, SessionStatus::Failed, msg, None).await
    }

    pub async fn mark_completed(&self, uuid: &Uuid, msg: &str) -> AppResult<()> {
        self.mark_session_status(uuid, SessionStatus::Completed, msg, None)
            .await
    }

    pub async fn mark_uncompleted(&self, uuid: &Uuid, msg: &str) -> AppResult<()> {
        self.mark_session_status(uuid, SessionStatus::Uncompleted, msg, None)
            .await
    }

    pub async fn is_session_blocked(&self, uuid: &Uuid) -> AppResult<bool> {
        match self.load_session(uuid).await? {
            Some(s) => Ok(s.is_blocked),
            None => Err(not_found(uuid)),
        }
    }

    pub async fn set_lock(&self, uuid: &Uuid, lock: bool) -> AppResult<bool> {
        let mut tx = self.pool.begin().await.map_err(db_error)?;
        let res = sqlx::query("UPDATE sessions SET is_blocked = $1, updated_at = $2 WHERE sessions.uuid = $3")
            .bind(lock)
            .bind(now_micros())
            .bind(uuid)
            .execute(&mut *tx)
            .await
            .map_err(db_error)?;
        tx.commit().await.map_err(db_error)?;
        let updated = res.rows_affected() == 1;
        if updated {
            // is_blocked is part of the cached detail aggregate.
            self.cache.invalidate(&[&k_detail(uuid)]).await;
        }
        Ok(updated)
    }

    // --- rounds / artifacts (written only while a session is live) ---------------

    /// Open the next generation round for a session, returning its pk.
    pub async fn create_round(&self, uuid: &Uuid, query: &str) -> AppResult<i64> {
        let Some(sid) = self.map_session_id(uuid).await? else {
            return Err(not_found(uuid));
        };
        let last = sqlx::query("SELECT number FROM rounds WHERE session_id = $1 ORDER BY number DESC LIMIT 1")
            .bind(i4(sid))
            .fetch_optional(&self.pool)
            .await
            .map_err(db_error)?;
        let number = match last {
            Some(r) => r.try_get::<i32, _>("number").map_err(db_error)? + 1,
            None => 1,
        };
        let now = now_micros();
        let mut qb =
            QueryBuilder::new("INSERT INTO rounds (session_id, number, query, created_at, updated_at) VALUES (");
        qb.push_bind(i4(sid))
            .push(", ")
            .push_bind(number)
            .push(", ")
            .push_bind(query.to_string())
            .push(", ")
            .push_bind(now)
            .push(", ")
            .push_bind(now)
            .push(")");
        self.insert_returning_id(qb).await
    }

    async fn create_artifact(&self, uri: &str, content_type: &str, file_size_bytes: i64) -> AppResult<i64> {
        let now = now_micros();
        let mut qb = QueryBuilder::new(
            "INSERT INTO artifacts (uri, content_type, file_size_bytes, created_at, updated_at) VALUES (",
        );
        qb.push_bind(uri.to_string())
            .push(", ")
            .push_bind(content_type.to_string())
            .push(", ")
            .push_bind(i4(file_size_bytes))
            .push(", ")
            .push_bind(now)
            .push(", ")
            .push_bind(now)
            .push(")");
        self.insert_returning_id(qb).await
    }

    pub async fn add_report(
        &self,
        round_id: i64,
        report_type: ReportType,
        uri: &str,
        content_type: &str,
        size: i64,
    ) -> AppResult<i64> {
        let aid = self.create_artifact(uri, content_type, size).await?;
        let now = now_micros();
        let mut qb =
            QueryBuilder::new("INSERT INTO reports (round_id, artifact_id, type, created_at, updated_at) VALUES (");
        qb.push_bind(i4(round_id))
            .push(", ")
            .push_bind(i4(aid))
            .push(", ")
            .push_bind(report_type.name())
            .push("::reporttype, ")
            .push_bind(now)
            .push(", ")
            .push_bind(now)
            .push(")");
        self.insert_returning_id(qb).await
    }

    pub async fn add_compliance_check(
        &self,
        round_id: i64,
        passed: bool,
        uri: &str,
        content_type: &str,
        size: i64,
    ) -> AppResult<i64> {
        let aid = self.create_artifact(uri, content_type, size).await?;
        let now = now_micros();
        let mut qb = QueryBuilder::new(
            "INSERT INTO compliance_checks (round_id, artifact_id, passed, created_at, updated_at) VALUES (",
        );
        qb.push_bind(i4(round_id))
            .push(", ")
            .push_bind(i4(aid))
            .push(", ")
            .push_bind(passed)
            .push(", ")
            .push_bind(now)
            .push(", ")
            .push_bind(now)
            .push(")");
        self.insert_returning_id(qb).await
    }

    pub async fn add_terraform_plan(
        &self,
        round_id: i64,
        targets: &[String],
        uri: &str,
        content_type: &str,
        size: i64,
    ) -> AppResult<i64> {
        let aid = self.create_artifact(uri, content_type, size).await?;
        let now = now_micros();
        let mut qb = QueryBuilder::new(
            "INSERT INTO terraform_plans (round_id, artifact_id, targets, created_at, updated_at) VALUES (",
        );
        qb.push_bind(i4(round_id))
            .push(", ")
            .push_bind(i4(aid))
            .push(", ")
            .push_bind(targets.to_vec())
            .push("::varchar[], ")
            .push_bind(now)
            .push(", ")
            .push_bind(now)
            .push(")");
        self.insert_returning_id(qb).await
    }

    pub async fn add_code_change(
        &self,
        round_id: i64,
        file_name: &str,
        uri: &str,
        content_type: &str,
        size: i64,
    ) -> AppResult<i64> {
        let aid = self.create_artifact(uri, content_type, size).await?;
        let now = now_micros();
        let mut qb = QueryBuilder::new(
            "INSERT INTO code_changes (round_id, artifact_id, file_name, created_at, updated_at) VALUES (",
        );
        qb.push_bind(i4(round_id))
            .push(", ")
            .push_bind(i4(aid))
            .push(", ")
            .push_bind(file_name.to_string())
            .push(", ")
            .push_bind(now)
            .push(", ")
            .push_bind(now)
            .push(")");
        self.insert_returning_id(qb).await
    }

    pub async fn get_pull_requests(&self, uuid: &Uuid) -> AppResult<Vec<PullRequestRef>> {
        let prs = self.pull_requests(uuid).await?;
        if prs.is_empty() {
            return Err(AppError::kind(
                ErrorKind::SessionTerminal,
                format!("Session {uuid} does not have any associated Pull Requests"),
                404,
            ));
        }
        prs.into_iter()
            .map(|p| serde_json::from_value::<PullRequestRef>(p).map_err(|e| AppError::internal(e.to_string())))
            .collect()
    }

    /// Persist a new pull request on the session's latest round and
    /// write-through the refreshed list.
    pub async fn add_pull_request(&self, uuid: &Uuid, url: &str, number: i64) -> AppResult<()> {
        let Some(sid) = self.map_session_id(uuid).await? else {
            return Err(not_found(uuid));
        };
        let Some(round_id) = self.latest_round_id(sid).await? else {
            return Err(AppError::kind(
                ErrorKind::SessionConflict,
                format!("Session {uuid} has no rounds; cannot attach a pull request."),
                409,
            ));
        };
        let now = now_micros();
        let mut qb = QueryBuilder::new(
            "INSERT INTO pull_requests (round_id, provider, number, url, created_at, updated_at) VALUES (",
        );
        qb.push_bind(i4(round_id))
            .push(", ")
            .push_bind(self.cfg.git.provider.name())
            .push("::gitprovidername, ")
            .push_bind(i4(number))
            .push(", ")
            .push_bind(url.to_string())
            .push(", ")
            .push_bind(now)
            .push(", ")
            .push_bind(now)
            .push(")");
        self.insert_returning_id(qb).await?;
        let prs = self.load_pull_requests(Some(sid)).await?;
        self.cache
            .set_json(&k_pull_requests(uuid), &prs, Some(ttl(TTL_PR)))
            .await;
        self.cache.invalidate(&[&k_detail(uuid)]).await;
        Ok(())
    }
}

/// The rows of `rows` whose `round_id` is `rid`, in order.
fn rows_of_round(rows: &[PgRow], rid: i32) -> AppResult<Vec<&PgRow>> {
    let mut v = Vec::new();
    for row in rows {
        if row.try_get::<i32, _>("round_id").map_err(db_error)? == rid {
            v.push(row);
        }
    }
    Ok(v)
}

fn parse_json_column(row: &PgRow, column: &str) -> AppResult<Value> {
    let raw: Option<String> = row.try_get(column).map_err(db_error)?;
    match raw {
        None => Ok(Value::Null),
        Some(text) => {
            serde_json::from_str(&text).map_err(|e| AppError::internal(format!("invalid JSON in {column}: {e}")))
        }
    }
}

#[allow(dead_code)]
fn empty_object() -> Value {
    Value::Object(Map::new())
}
