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
