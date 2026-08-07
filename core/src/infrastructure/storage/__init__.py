# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from src.infrastructure.storage.factory import (
    ObjectStorageFactory,
    default_object_storage,
)

__all__ = [
    "ObjectStorageFactory",
    "default_object_storage",
]
