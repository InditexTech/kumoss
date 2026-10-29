// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

//! Uploads round artifacts to object storage and records the DB rows.
//!
//! The stored `artifacts.uri` is the object KEY; the session read model
//! presigns it at read time. Upload happens before the row insert; a failed
//! insert triggers a best-effort compensating delete so no row ever points
//! at a missing object, while an orphaned object is harmless garbage.

use std::future::Future;
use std::sync::{Arc, LazyLock};

use regex::Regex;
use uuid::Uuid;

use crate::domain::ports::{ObjectMetadata, ObjectStorage};
use crate::domain::services::database::DatabaseService;
use crate::shared::constants::{ContentType, ReportType};
use crate::shared::error::{AppError, AppResult, ErrorKind};

/// Object keys keep a sanitized copy of user-provided file names; the
/// untouched original lives in the database.
static UNSAFE_NAME_CHARS: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"[^A-Za-z0-9._-]+").unwrap());
const MAX_NAME_LEN: usize = 100;

fn safe_name(file_name: &str) -> String {
    let replaced = UNSAFE_NAME_CHARS.replace_all(file_name, "_");
    let truncated = crate::shared::pyfmt::take_chars(&replaced, MAX_NAME_LEN);
    if truncated.is_empty() {
        "file".into()
    } else {
        truncated.to_string()
    }
}

/// A round stores several plans and reports, and the read model returns
/// them all: a random token keeps each write at a fresh key so an old DB
/// row can never alias new bytes.
fn token() -> String {
    Uuid::new_v4().simple().to_string()[..8].to_string()
}

#[derive(Clone)]
pub struct ArtifactStorageService {
    storage: Arc<dyn ObjectStorage>,
    db: DatabaseService,
}

impl ArtifactStorageService {
    pub fn new(storage: Arc<dyn ObjectStorage>, db: DatabaseService) -> Self {
        Self { storage, db }
    }

    /// Persist a round report; returns the reports row pk.
    pub async fn store_report(
        &self,
        session_id: &Uuid,
        round_id: i64,
        report_type: ReportType,
        content: &str,
        content_type: ContentType,
        metadata: ObjectMetadata,
    ) -> AppResult<i64> {
        let data = content.as_bytes().to_vec();
        let key = format!(
            "sessions/{session_id}/rounds/{round_id}/reports/{}-{}.json",
            report_type.value(),
            token()
        );
        let size = data.len() as i64;
        let db = self.db.clone();
        let k = key.clone();
        self.store(
            &key,
            data,
            content_type.value(),
            metadata,
            &format!("session {session_id} round {round_id}"),
            async move {
                db.add_report(round_id, report_type, &k, content_type.value(), size)
                    .await
            },
        )
        .await
    }

    /// Persist a round compliance check; returns the compliance_checks row pk.
    pub async fn store_compliance_check(
        &self,
        session_id: &Uuid,
        round_id: i64,
        passed: bool,
        content: &str,
        content_type: ContentType,
        metadata: ObjectMetadata,
    ) -> AppResult<i64> {
        let data = content.as_bytes().to_vec();
        let key = format!(
            "sessions/{session_id}/rounds/{round_id}/compliance/check-{}.json",
            token()
        );
        let size = data.len() as i64;
        let db = self.db.clone();
        let k = key.clone();
        self.store(
            &key,
            data,
            content_type.value(),
            metadata,
            &format!("session {session_id} round {round_id}"),
            async move {
                db.add_compliance_check(round_id, passed, &k, content_type.value(), size)
                    .await
            },
        )
        .await
    }

    /// Persist a round terraform plan; returns the terraform_plans row pk.
    /// The row holds no flavour, so callers storing more than one kind of
    /// plan (a drift diff and a validation plan) label it in `metadata`.
    pub async fn store_terraform_plan(
        &self,
        session_id: &Uuid,
        round_id: i64,
        targets: &[String],
        content: &str,
        content_type: ContentType,
        metadata: ObjectMetadata,
    ) -> AppResult<i64> {
        let data = content.as_bytes().to_vec();
        let key = format!("sessions/{session_id}/rounds/{round_id}/plans/{}.txt", token());
        let size = data.len() as i64;
        let db = self.db.clone();
        let k = key.clone();
        let targets = targets.to_vec();
        self.store(
            &key,
            data,
            content_type.value(),
            metadata,
            &format!("session {session_id} round {round_id}"),
            async move {
                db.add_terraform_plan(round_id, &targets, &k, content_type.value(), size)
                    .await
            },
        )
        .await
    }

    /// Persist a round code change; `file_name` is stored verbatim in the
    /// DB and sanitized inside the object key.
    pub async fn store_code_change(
        &self,
        session_id: &Uuid,
        round_id: i64,
        file_name: &str,
        content: &str,
        content_type: ContentType,
        metadata: ObjectMetadata,
    ) -> AppResult<i64> {
        let data = content.as_bytes().to_vec();
        let key = format!(
            "sessions/{session_id}/rounds/{round_id}/changes/{}-{}",
            token(),
            safe_name(file_name)
        );
        let size = data.len() as i64;
        let db = self.db.clone();
        let k = key.clone();
        let name = file_name.to_string();
        self.store(
            &key,
            data,
            content_type.value(),
            metadata,
            &format!("session {session_id} round {round_id}"),
            async move {
                db.add_code_change(round_id, &name, &k, content_type.value(), size)
                    .await
            },
        )
        .await
    }

    /// Upload-then-record; compensating delete keeps rows truthful.
    async fn store(
        &self,
        key: &str,
        data: Vec<u8>,
        content_type: &str,
        metadata: ObjectMetadata,
        context: &str,
        db_write: impl Future<Output = AppResult<i64>>,
    ) -> AppResult<i64> {
        if content_type.len() > 64 {
            return Err(AppError::kind(
                ErrorKind::ObjectStorage,
                format!(
                    "content_type too long for artifacts.content_type (max 64): {}",
                    crate::shared::pyfmt::repr_str(content_type)
                ),
                400,
            ));
        }
        self.storage.put(key, data, content_type, &metadata).await?;
        match db_write.await {
            Ok(id) => Ok(id),
            Err(e) => {
                self.compensate(key).await;
                if e.kind == ErrorKind::Internal {
                    return Err(AppError::kind(
                        ErrorKind::ObjectStorage,
                        format!("Recording artifact '{key}' failed ({context}): {}", e.message),
                        500,
                    ));
                }
                Err(e)
            }
        }
    }

    async fn compensate(&self, key: &str) {
        // Best-effort: an orphaned object is recoverable garbage, unlike a
        // DB row pointing at a missing object.
        if let Err(e) = self.storage.delete(key).await {
            tracing::warn!("Compensating delete of '{key}' failed: {e}");
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn safe_names() {
        assert_eq!(safe_name("modules/net/main.tf"), "modules_net_main.tf");
        assert_eq!(safe_name("a b@c"), "a_b_c");
        assert_eq!(safe_name(""), "file");
        assert_eq!(safe_name(&"x".repeat(150)).len(), 100);
    }

    #[test]
    fn token_is_8_hex() {
        let t = token();
        assert_eq!(t.len(), 8);
        assert!(t.chars().all(|c| c.is_ascii_hexdigit()));
    }
}
