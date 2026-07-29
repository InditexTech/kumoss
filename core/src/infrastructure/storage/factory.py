# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from functools import cache

from src.domains.interfaces import IObjectStorage
from src.infrastructure.storage._s3 import S3ObjectStorage
from src.shared.config import system_config
from src.shared.constants import ObjectStorageProvider


# Lazily initialized singletons.
@cache
def _rustfs() -> S3ObjectStorage:
    cfg = system_config.storage
    return S3ObjectStorage(
        bucket=cfg.bucket,
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
def _s3() -> S3ObjectStorage:
    cfg = system_config.storage
    return S3ObjectStorage(
        bucket=cfg.bucket,
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


class ObjectStorageFactory:
    def __init__(self, provider: ObjectStorageProvider):
        self.__provider = provider

    def get(self) -> IObjectStorage:
        match self.__provider:
            case ObjectStorageProvider.RUSTFS:
                return _rustfs()
            case ObjectStorageProvider.S3:
                return _s3()
            case _:
                raise NotImplementedError()


def default_object_storage() -> IObjectStorage:
    """The config-selected adapter singleton.

    Cheap enough for sync call sites (cached construction, no IO).
    """
    return ObjectStorageFactory(system_config.storage.provider).get()
