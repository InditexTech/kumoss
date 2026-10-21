from enum import StrEnum


class SubjectType(StrEnum):
    USER = "user"

    def __str__(self) -> str:
        return str(self.value)
