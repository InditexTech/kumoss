from enum import StrEnum


class ActionName(StrEnum):
    APPLY = "apply"
    DRIFT = "drift"
    GENERATE = "generate"
    IMPORT = "import"
    PR_CREATE = "pr.create"
    PR_MERGE = "pr.merge"

    def __str__(self) -> str:
        return str(self.value)
