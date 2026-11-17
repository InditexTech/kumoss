# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from enum import StrEnum


class ResourcePropertiesProvider(StrEnum):
    AWS = "aws"
    AZURE = "azure"
    GCP = "gcp"
    KUBERNETES = "kubernetes"
    OCI = "oci"
    VMWARE = "vmware"

    def __str__(self) -> str:
        return str(self.value)
