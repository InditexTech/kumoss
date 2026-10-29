// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

//! Object storage adapters and the config-driven factory that picks one.

pub mod azure;
pub mod s3;

use std::collections::HashMap;
use std::sync::{Arc, LazyLock, Mutex};

use tokio::sync::OnceCell;

pub use azure::{AzureOptions, StorageAccountObjectStorage};
pub use s3::{S3ObjectStorage, S3Options};

use crate::domain::ports::ObjectStorage;
use crate::shared::config::{StorageConfig, system_config};
use crate::shared::constants::ObjectStorageProvider;
use crate::shared::error::{AppError, AppResult};

fn max_attempts(cfg: &StorageConfig) -> u32 {
    u32::try_from(cfg.max_attempts.max(0)).unwrap_or(u32::MAX)
}

fn presign_expiry(cfg: &StorageConfig) -> u64 {
    u64::try_from(cfg.presign_expiry_seconds.max(0)).unwrap_or(0)
}

/// RUSTFS, or any custom-endpoint S3-compatible server: path-style on
/// `endpoint_url`, presigning against `public_endpoint_url`.
pub async fn rustfs(cfg: &StorageConfig, bucket: &str) -> S3ObjectStorage {
    S3ObjectStorage::new(S3Options {
        bucket: bucket.to_string(),
        region: cfg.region.clone(),
        endpoint_url: Some(cfg.endpoint_url.clone()),
        public_endpoint_url: Some(cfg.public_endpoint_url.clone()),
        access_key: Some(cfg.access_key()),
        secret_key: Some(cfg.secret_key()),
        presign_expiry_seconds: presign_expiry(cfg),
        force_path_style: true,
        connect_timeout: cfg.connect_timeout,
        read_timeout: cfg.read_timeout,
        max_attempts: max_attempts(cfg),
    })
    .await
}

/// Real AWS S3: regional default endpoints, virtual-hosted addressing, static
/// keys only when both are set (else the default credential chain).
pub async fn s3(cfg: &StorageConfig, bucket: &str) -> S3ObjectStorage {
    let non_empty = |v: String| if v.is_empty() { None } else { Some(v) };
    S3ObjectStorage::new(S3Options {
        bucket: bucket.to_string(),
        region: cfg.region.clone(),
        endpoint_url: None,
        public_endpoint_url: None,
        access_key: non_empty(cfg.access_key()),
        secret_key: non_empty(cfg.secret_key()),
        presign_expiry_seconds: presign_expiry(cfg),
        force_path_style: false,
        connect_timeout: cfg.connect_timeout,
        read_timeout: cfg.read_timeout,
        max_attempts: max_attempts(cfg),
    })
    .await
}

/// A public Azure storage account (or an emulator); `container` is the blob
/// container and the account name is derived from `endpoint_url`.
pub fn storage_account(cfg: &StorageConfig, container: &str) -> AppResult<StorageAccountObjectStorage> {
    let account = cfg.storage_account_name().map_err(|e| AppError::internal(e.0))?;
    StorageAccountObjectStorage::new(AzureOptions {
        container: container.to_string(),
        account,
        endpoint_url: cfg.endpoint_url.clone(),
        public_endpoint_url: Some(cfg.public_endpoint_url.clone()),
        account_key: cfg.account_key(),
        presign_expiry_seconds: presign_expiry(cfg),
        connect_timeout: cfg.connect_timeout,
        read_timeout: cfg.read_timeout,
        max_attempts: max_attempts(cfg),
    })
}

type Slot = Arc<OnceCell<Arc<dyn ObjectStorage>>>;

/// Lazily initialized singletons, one per (provider, bucket) pair: the
/// Terraform state bucket is the same store as the artifacts bucket, reached
/// with the same credentials, so it differs only in the name.
static INSTANCES: LazyLock<Mutex<HashMap<(ObjectStorageProvider, String), Slot>>> =
    LazyLock::new(|| Mutex::new(HashMap::new()));

/// The cached adapter for `provider` on `bucket`, built from `cfg` on first
/// use (the Python `ObjectStorageFactory(provider, bucket).get()`).
pub async fn object_storage(
    cfg: &StorageConfig,
    provider: ObjectStorageProvider,
    bucket: &str,
) -> AppResult<Arc<dyn ObjectStorage>> {
    let slot: Slot = {
        let mut instances = INSTANCES.lock().unwrap_or_else(|poisoned| poisoned.into_inner());
        Arc::clone(instances.entry((provider, bucket.to_string())).or_default())
    };
    slot.get_or_try_init(|| async {
        let storage: Arc<dyn ObjectStorage> = match provider {
            ObjectStorageProvider::Rustfs => Arc::new(rustfs(cfg, bucket).await),
            ObjectStorageProvider::S3 => Arc::new(s3(cfg, bucket).await),
            ObjectStorageProvider::StorageAccount => Arc::new(storage_account(cfg, bucket)?),
        };
        Ok::<_, AppError>(storage)
    })
    .await
    .cloned()
}

/// The config-selected adapter for the artifacts bucket, from `cfg`.
pub async fn default_object_storage_for(cfg: &StorageConfig) -> AppResult<Arc<dyn ObjectStorage>> {
    object_storage(cfg, cfg.provider, &cfg.bucket).await
}

/// The same store bound to the Terraform state bucket, from `cfg`; None when
/// `storage.terraform_state_bucket` is empty.
pub async fn terraform_state_storage_for(cfg: &StorageConfig) -> AppResult<Option<Arc<dyn ObjectStorage>>> {
    let bucket = cfg.state_bucket();
    if bucket.is_empty() {
        return Ok(None);
    }
    object_storage(cfg, cfg.provider, &bucket).await.map(Some)
}

/// The config-selected adapter singleton for the artifacts bucket.
pub async fn default_object_storage() -> AppResult<Arc<dyn ObjectStorage>> {
    default_object_storage_for(&system_config().storage).await
}

/// The same store, bound to the Terraform state bucket.
///
/// None when `storage.terraform_state_bucket` is empty, which turns managed
/// state off: no backend override is written and each workspace keeps the
/// backend its own configuration declares.
pub async fn terraform_state_storage() -> AppResult<Option<Arc<dyn ObjectStorage>>> {
    terraform_state_storage_for(&system_config().storage).await
}

#[cfg(test)]
mod tests {
    //! Adapter selection. Construction does no IO and is cached per
    //! (provider, bucket), so these run without a store.

    use super::*;
    use crate::shared::config::test_support::test_config;
    use serde_json::json;

    fn storage_config(overrides: serde_json::Value) -> StorageConfig {
        test_config(json!({ "storage": overrides })).storage
    }

    fn same(a: &Arc<dyn ObjectStorage>, b: &Arc<dyn ObjectStorage>) -> bool {
        std::ptr::addr_eq(Arc::as_ptr(a), Arc::as_ptr(b))
    }

    #[tokio::test]
    async fn unset_state_bucket_turns_managed_state_off() {
        for raw in ["", "   "] {
            let cfg = storage_config(json!({"terraform_state_bucket": raw, "bucket": "artifacts-off"}));
            assert!(terraform_state_storage_for(&cfg).await.unwrap().is_none(), "{raw:?}");
        }
    }

    #[tokio::test]
    async fn the_state_store_is_the_artifacts_store_on_another_bucket() {
        let cfg = storage_config(json!({"bucket": "artifacts-a", "terraform_state_bucket": "state-a"}));
        let state = terraform_state_storage_for(&cfg).await.unwrap().unwrap();
        let cached = object_storage(&cfg, ObjectStorageProvider::Rustfs, "state-a")
            .await
            .unwrap();
        assert!(same(&state, &cached));
        let artifacts = default_object_storage_for(&cfg).await.unwrap();
        assert!(!same(&state, &artifacts));
        assert!(same(&artifacts, &default_object_storage_for(&cfg).await.unwrap()));
    }

    #[tokio::test]
    async fn every_provider_answers_a_usable_prefix() {
        // SAFETY: test-only constant values.
        unsafe { std::env::set_var("KUMOSS_TEST_STORAGE_ACCOUNT_KEY", "a2V5") };
        for provider in ObjectStorageProvider::ALL {
            let endpoint = match provider {
                ObjectStorageProvider::StorageAccount => "https://kumoss.blob.core.windows.net",
                _ => "http://object-storage:9000",
            };
            let cfg = storage_config(json!({
                "provider": provider.name(),
                "endpoint_url": endpoint,
                "account_key_env": "KUMOSS_TEST_STORAGE_ACCOUNT_KEY",
                "bucket": format!("prefix-probe-{}", provider.name()).to_lowercase(),
            }));
            let prefix = default_object_storage_for(&cfg).await.unwrap().metadata_header_prefix();
            assert!(
                prefix.starts_with("x-") && prefix.ends_with('-'),
                "{provider:?}: {prefix}"
            );
        }
    }

    #[tokio::test]
    async fn the_two_s3_providers_share_the_amazon_prefix() {
        let cfg = storage_config(json!({}));
        let rustfs = object_storage(&cfg, ObjectStorageProvider::Rustfs, "a").await.unwrap();
        let s3 = object_storage(&cfg, ObjectStorageProvider::S3, "b").await.unwrap();
        assert_eq!(rustfs.metadata_header_prefix(), s3.metadata_header_prefix());
    }
}
