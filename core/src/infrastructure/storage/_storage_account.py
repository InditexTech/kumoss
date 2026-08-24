# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from datetime import datetime, timedelta, timezone
from typing import NoReturn, final, override
from urllib.parse import quote

from azure.core.exceptions import (
    ResourceExistsError,
    ResourceNotFoundError,
    ServiceRequestError,
    ServiceResponseError,
)
from azure.storage.blob import (
    BlobSasPermissions,
    BlobServiceClient,
    ContentSettings,
    generate_blob_sas,
)

from src.domains.exceptions import (
    ObjectNotFound,
    ObjectStorageError,
    ObjectStorageUnavailable,
)
from src.domains.interfaces import IObjectStorage
from src.shared.logger import logging
from src.shared.utils.decorators import execute_pool


@final
class StorageAccountObjectStorage(IObjectStorage):
    """Azure storage-account adapter over the sync blob SDK.

    Blocking SDK calls run on the shared ``execute_pool`` thread pool;
    SAS generation is local HMAC over the account key and stays sync.

    The account name is not configured separately: the config layer
    derives it from ``endpoint_url`` (see ``StorageConfig``). An account-key SAS
    signs the canonical resource path — so browser URLs are string-built
    on ``public_endpoint_url`` while SDK calls hit ``endpoint_url``.
    For a real public storage account both are the same host; they differ only
    in emulator-style split setups.
    """

    def __init__(
        self,
        *,
        container: str,
        account: str,
        endpoint_url: str,
        public_endpoint_url: str | None,
        account_key: str,
        presign_expiry_seconds: int,
        connect_timeout: float = 3.0,
        read_timeout: float = 10.0,
        max_attempts: int = 3,
    ):
        """Args:
        container: Container holding every object this adapter touches.
        account: Account name (derived from ``endpoint_url`` by the
            config layer; passed explicitly because SAS signing and
            path-style endpoints cannot re-derive it reliably).
        endpoint_url: Account blob endpoint for SDK calls,
            ``https://<account>.blob.core.windows.net`` or an
            emulator-style ``http://<host>:<port>/<account>``.
        public_endpoint_url: Base for browser-facing SAS URLs; None or
            equal to ``endpoint_url`` reuses the SDK endpoint.
        account_key: Shared key for SDK calls and local SAS signing.
        presign_expiry_seconds: Default validity of SAS GET URLs.
        connect_timeout: Seconds to establish a connection.
        read_timeout: Seconds to wait on a response.
        max_attempts: SDK retry budget.
        """
        self.__container = container
        self.__account = account
        self.__account_key = account_key
        self.__presign_expiry = presign_expiry_seconds
        self.__public_base = (public_endpoint_url or endpoint_url).rstrip("/")

        # SDK clients are thread-safe: build once, share across pool calls.
        # Dict credential: with path-style endpoints the SDK would parse
        # the wrong account name out of the URL for request signing.
        self.__client = BlobServiceClient(
            account_url=endpoint_url,
            credential={"account_name": account, "account_key": account_key},
            connection_timeout=connect_timeout,
            read_timeout=read_timeout,
            retry_total=max_attempts,
        )

    def __raise_translated(self, e: Exception, op: str, key: str) -> NoReturn:
        """Map any SDK failure onto the domain exceptions (port contract)."""
        target = f"{self.__container}/{key}" if key else self.__container
        logging.error(f"Object storage {op} failed on '{target}': {e}")
        if isinstance(e, (ServiceRequestError, ServiceResponseError)):
            # Request never sent / response never received: connectivity.
            raise ObjectStorageUnavailable(
                message=f"Object store unreachable during {op} on '{target}'.",
                error_code=503,
            ) from e
        if isinstance(e, ResourceNotFoundError):
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
            _ = self.__client.create_container(self.__container)
        except ResourceExistsError:
            # Already there, or two replicas racing the same boot.
            pass

    @execute_pool
    def __put_sync(
        self, key: str, data: bytes, content_type: str, metadata: dict[str, str]
    ) -> None:
        # overwrite=True: parity with S3 put semantics (last write wins).
        _ = self.__client.get_blob_client(self.__container, key).upload_blob(
            data,
            overwrite=True,
            content_settings=ContentSettings(content_type=content_type),
            metadata=metadata,
        )

    @execute_pool
    def __get_sync(self, key: str) -> bytes:
        # The body stream read is blocking IO too: keep it in the pool call.
        blob = self.__client.get_blob_client(self.__container, key)
        return blob.download_blob().readall()

    @execute_pool
    def __exists_sync(self, key: str) -> bool:
        return self.__client.get_blob_client(self.__container, key).exists()

    @execute_pool
    def __delete_sync(self, key: str) -> None:
        try:
            self.__client.get_blob_client(self.__container, key).delete_blob()
        except ResourceNotFoundError:
            # Azure 404s absent keys; the port wants idempotent deletes.
            pass

    # --- port surface --------------------------------------------------------

    @override
    async def ensure_bucket(self) -> None:
        try:
            await self.__ensure_bucket_sync()
        except Exception as e:
            self.__raise_translated(e, "ensure_bucket", "")

    @override
    async def put(
        self, key: str, data: bytes, content_type: str, metadata: dict[str, str]
    ) -> None:
        try:
            await self.__put_sync(key, data, content_type, metadata)
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
            sas = generate_blob_sas(
                account_name=self.__account,
                container_name=self.__container,
                blob_name=key,
                account_key=self.__account_key,
                permission=BlobSasPermissions(read=True),
                expiry=datetime.now(timezone.utc)
                + timedelta(seconds=expires_in or self.__presign_expiry),
            )
            # SAS binds the resource path, not the host: safe to build on
            # whichever base the browser reaches.
            return f"{self.__public_base}/{self.__container}/{quote(key)}?{sas}"
        except Exception as e:
            self.__raise_translated(e, "presign", key)
