# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from typing import Any, NoReturn, final, override

import boto3
from botocore.client import Config as BotoConfig
from botocore.exceptions import (
    ClientError,
    ConnectTimeoutError,
    EndpointConnectionError,
    ReadTimeoutError,
)

from src.domains.exceptions import (
    ObjectNotFound,
    ObjectStorageError,
    ObjectStorageUnavailable,
)
from src.domains.interfaces import IObjectStorage
from src.shared.logger import logging
from src.shared.utils.decorators import execute_pool

_NOT_FOUND_CODES = frozenset({"404", "NoSuchKey", "NoSuchBucket"})
_ALREADY_OWNED_CODES = frozenset({"BucketAlreadyOwnedByYou", "BucketAlreadyExists"})


def _error_code(e: ClientError) -> str:
    return str(e.response.get("Error", {}).get("Code", ""))


@final
class AWSObjectStorage(IObjectStorage):
    """S3-API adapter over sync boto3 (RustFS, MinIO, AWS S3).

    Blocking SDK calls run on the shared ``execute_pool`` thread pool;
    presigning is pure local computation and stays sync.

    Two clients exist because SigV4 binds the Host header: ``__client``
    talks to the store on the internal endpoint, while URLs handed to
    the browser must be signed against the host the browser will fetch,
    so ``__presign`` is built on ``public_endpoint_url`` (it never
    touches the network). With no custom endpoints (AWS) a single client
    on the regional default serves both roles.

    No boto3/botocore exception escapes this class: everything is
    translated to the ExceptionHandler-based domain exceptions.
    """

    def __init__(
        self,
        *,
        bucket: str,
        region: str,
        endpoint_url: str | None,
        public_endpoint_url: str | None,
        access_key: str | None,
        secret_key: str | None,
        presign_expiry_seconds: int,
        force_path_style: bool = True,
        connect_timeout: float = 3.0,
        read_timeout: float = 10.0,
        max_attempts: int = 3,
    ):
        """Args:
        bucket: Bucket holding every object this adapter touches.
        region: AWS region (drives the default endpoint when
            ``endpoint_url`` is None).
        endpoint_url: Custom S3 endpoint for SDK calls; None means the
            AWS regional default.
        public_endpoint_url: Host presigned URLs are signed against;
            None or equal to ``endpoint_url`` reuses the main client.
        access_key: Static credentials; None/empty defers to boto3's
            default credential chain (env vars, profile, IAM role).
        secret_key: Counterpart of ``access_key``.
        presign_expiry_seconds: Default validity of presigned GET URLs.
        force_path_style: Path-style addressing (custom endpoints) vs
            virtual-hosted (AWS).
        connect_timeout: Seconds to establish a connection.
        read_timeout: Seconds to wait on a response.
        max_attempts: botocore standard-mode retry budget.
        """
        self.__bucket = bucket
        self.__region = region
        self.__endpoint_url = endpoint_url
        self.__presign_expiry = presign_expiry_seconds

        config = BotoConfig(
            signature_version="s3v4",
            s3={"addressing_style": "path" if force_path_style else "virtual"},
            retries={"max_attempts": max_attempts, "mode": "standard"},
            connect_timeout=connect_timeout,
            read_timeout=read_timeout,
        )
        credentials: dict[str, str] = (
            {"aws_access_key_id": access_key, "aws_secret_access_key": secret_key}
            if access_key and secret_key
            else {}
        )
        # boto3 clients are thread-safe: build once, share across pool calls.
        self.__client: Any = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            region_name=region,
            config=config,
            **credentials,
        )
        self.__presign: Any = (
            boto3.client(
                "s3",
                endpoint_url=public_endpoint_url,
                region_name=region,
                config=config,
                **credentials,
            )
            if public_endpoint_url and public_endpoint_url != endpoint_url
            else self.__client
        )

    def __raise_translated(self, e: Exception, op: str, key: str) -> NoReturn:
        """Map any SDK failure onto the domain exceptions (port contract)."""
        target = f"{self.__bucket}/{key}" if key else self.__bucket
        logging.error(f"Object storage {op} failed on '{target}': {e}")
        if isinstance(
            e, (EndpointConnectionError, ConnectTimeoutError, ReadTimeoutError)
        ):
            raise ObjectStorageUnavailable(
                message=f"Object store unreachable during {op} on '{target}'.",
                error_code=503,
            ) from e
        if isinstance(e, ClientError) and _error_code(e) in _NOT_FOUND_CODES:
            raise ObjectNotFound(
                message=f"Object '{target}' not found.",
                error_code=404,
            ) from e
        raise ObjectStorageError(
            message=f"Object storage {op} failed on '{target}': {e}",
            error_code=500,
        ) from e

    # --- sync bodies, offloaded to the shared thread pool -------------------
    # execute_pool forwards positional args only: call these positionally.

    @execute_pool
    def __ensure_bucket_sync(self) -> None:
        try:
            self.__client.head_bucket(Bucket=self.__bucket)
            return
        except ClientError as e:
            if _error_code(e) not in _NOT_FOUND_CODES:
                raise
        params: dict[str, Any] = {"Bucket": self.__bucket}
        if self.__endpoint_url is None and self.__region != "us-east-1":
            # Only real AWS wants the location constraint.
            params["CreateBucketConfiguration"] = {"LocationConstraint": self.__region}
        try:
            self.__client.create_bucket(**params)
        except ClientError as e:
            # Two replicas racing the same boot is not an error.
            if _error_code(e) not in _ALREADY_OWNED_CODES:
                raise

    @execute_pool
    def __put_sync(self, key: str, data: bytes, content_type: str) -> None:
        self.__client.put_object(
            Bucket=self.__bucket, Key=key, Body=data, ContentType=content_type
        )

    @execute_pool
    def __get_sync(self, key: str) -> bytes:
        # The body stream read is blocking IO too: keep it in the pool call.
        response = self.__client.get_object(Bucket=self.__bucket, Key=key)
        return response["Body"].read()

    @execute_pool
    def __exists_sync(self, key: str) -> bool:
        try:
            self.__client.head_object(Bucket=self.__bucket, Key=key)
            return True
        except ClientError as e:
            if _error_code(e) in _NOT_FOUND_CODES:
                return False
            raise

    @execute_pool
    def __delete_sync(self, key: str) -> None:
        # S3 returns 204 for absent keys: naturally idempotent.
        self.__client.delete_object(Bucket=self.__bucket, Key=key)

    # --- port surface --------------------------------------------------------

    @override
    async def ensure_bucket(self) -> None:
        try:
            await self.__ensure_bucket_sync()
        except Exception as e:
            self.__raise_translated(e, "ensure_bucket", "")

    @override
    async def put(self, key: str, data: bytes, content_type: str) -> None:
        try:
            await self.__put_sync(key, data, content_type)
        except Exception as e:
            self.__raise_translated(e, "put", key)

    @override
    async def get(self, key: str) -> bytes:
        try:
            return await self.__get_sync(key)
        except Exception as e:
            self.__raise_translated(e, "get", key)

    @override
    async def exists(self, key: str) -> bool:
        try:
            return await self.__exists_sync(key)
        except Exception as e:
            self.__raise_translated(e, "exists", key)

    @override
    async def delete(self, key: str) -> None:
        try:
            await self.__delete_sync(key)
        except Exception as e:
            self.__raise_translated(e, "delete", key)

    @override
    def presigned_get_url(self, key: str, expires_in: int | None = None) -> str:
        try:
            return self.__presign.generate_presigned_url(
                ClientMethod="get_object",
                Params={"Bucket": self.__bucket, "Key": key},
                ExpiresIn=expires_in or self.__presign_expiry,
            )
        except Exception as e:
            self.__raise_translated(e, "presign", key)
