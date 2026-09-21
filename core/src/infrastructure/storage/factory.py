# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from functools import cache

from src.domains.interfaces import IObjectStorage
from src.infrastructure.storage._s3 import S3ObjectStorage
from src.infrastructure.storage._storage_account import StorageAccountObjectStorage
from src.shared.config import system_config
from src.shared.constants import ObjectStorageProvider


# Lazily initialized singletons, one per (provider, bucket) pair: the
# Terraform state bucket is the same store as the artifacts bucket,
# reached with the same credentials, so it differs only in the name.
@cache
def _rustfs(bucket: str) -> S3ObjectStorage:
    cfg = system_config.storage
    return S3ObjectStorage(
        bucket=bucket,
        region=cfg.region,
        endpoint_url=cfg.endpoint_url,
        public_endpoint_url=cfg.public_endpoint_url,
        access_key=cfg.access_key,
        secret_key=cfg.secret_key,
        presign_expiry_seconds=cfg.presign_expiry_seconds,
        force_path_style=True,
        connect_timeout=cfg.connect_timeout,
        read_timeout=cfg.read_timeout,
        max_attempts=cfg.max_attempts,
    )


@cache
def _s3(bucket: str) -> S3ObjectStorage:
    cfg = system_config.storage
    return S3ObjectStorage(
        bucket=bucket,
        region=cfg.region,
        endpoint_url=None,
        public_endpoint_url=None,
        access_key=cfg.access_key or None,
        secret_key=cfg.secret_key or None,
        presign_expiry_seconds=cfg.presign_expiry_seconds,
        force_path_style=False,
        connect_timeout=cfg.connect_timeout,
        read_timeout=cfg.read_timeout,
        max_attempts=cfg.max_attempts,
    )


@cache
def _storage_account(container: str) -> StorageAccountObjectStorage:
    cfg = system_config.storage
    return StorageAccountObjectStorage(
        container=container,
        account=cfg.storage_account_name,
        endpoint_url=cfg.endpoint_url,
        public_endpoint_url=cfg.public_endpoint_url,
        account_key=cfg.account_key,
        presign_expiry_seconds=cfg.presign_expiry_seconds,
        connect_timeout=cfg.connect_timeout,
        read_timeout=cfg.read_timeout,
        max_attempts=cfg.max_attempts,
    )


class ObjectStorageFactory:
    def __init__(self, provider: ObjectStorageProvider, bucket: str):
        self.__provider = provider
        self.__bucket = bucket

    def get(self) -> IObjectStorage:
        match self.__provider:
            case ObjectStorageProvider.RUSTFS:
                return _rustfs(self.__bucket)
            case ObjectStorageProvider.S3:
                return _s3(self.__bucket)
            case ObjectStorageProvider.STORAGE_ACCOUNT:
                return _storage_account(self.__bucket)
            case _:
                raise NotImplementedError()


def default_object_storage() -> IObjectStorage:
    """The config-selected adapter singleton for the artifacts bucket.

    Cheap enough for sync call sites (cached construction, no IO).
    """
    cfg = system_config.storage
    return ObjectStorageFactory(cfg.provider, cfg.bucket).get()


def terraform_state_storage() -> IObjectStorage | None:
    """The same store, bound to the Terraform state bucket.

    None when ``storage.terraform_state_bucket`` is empty, which turns
    managed state off: no backend override is written and each
    workspace keeps the backend its own configuration declares.
    """
    cfg = system_config.storage
    if not cfg.state_bucket:
        return None
    return ObjectStorageFactory(cfg.provider, cfg.state_bucket).get()
