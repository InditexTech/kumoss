from enum import StrEnum


class ResourceType(StrEnum):
    SCOPE = "scope"

    def __str__(self) -> str:
        return str(self.value)
