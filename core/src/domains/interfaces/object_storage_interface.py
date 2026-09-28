# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from abc import ABC, abstractmethod


class IObjectStorage(ABC):
    """Provider-agnostic blob store keyed by opaque string keys.

    Implementations translate every provider failure into the domain
    exceptions ``ObjectNotFound`` / ``ObjectStorageUnavailable`` /
    ``ObjectStorageError`` — no SDK exception may escape, so callers can
    uniformly catch ``ExceptionHandler``.
    """

    @abstractmethod
    async def ensure_bucket(self) -> None:
        """Create the backing bucket/container if missing. Idempotent."""
        pass

    @abstractmethod
    async def put(
        self, key: str, data: bytes, content_type: str, metadata: dict[str, str]
    ) -> None:
        """Store ``data`` at ``key``.

        Args:
            key: Opaque object key (no scheme, no bucket).
            data: Full object body.
            content_type: MIME type served back on reads.
            metadata: Metadata attached to the object.
        """
        pass

    @property
    @abstractmethod
    def metadata_header_prefix(self) -> str:
        """Prefix this store prepends to metadata keys on the way out.

        A browser reading an object's metadata off a presigned URL
        has to be told which prefix to ask for.
        """
        pass

    @abstractmethod
    async def get(self, key: str) -> bytes:
        """Full object body for ``key``.

        Raises:
            ObjectNotFound: When the key does not exist.
        """
        pass

    @abstractmethod
    async def exists(self, key: str) -> bool:
        """Whether ``key`` currently exists."""
        pass

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Remove ``key``. Deleting a missing key is a no-op (idempotent)."""
        pass

    @abstractmethod
    def presigned_get_url(self, key: str, expires_in: int | None = None) -> str:
        """Browser-fetchable time-limited GET URL for ``key``.

        Args:
            key: Object key to sign.
            expires_in: Validity in seconds; defaults to the configured
                expiry when None.
        """
        pass
