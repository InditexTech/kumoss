# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import json

from src.domains.dto import ToolCallDTO, ToolDefinitionDTO, ToolResultDTO


class ToolLoopState:
    """
    Memory of the tool calls executed during a single agent loop.

    The result of every executed call is already in the conversation, so:
    - a call identical to an executed one is a duplicate and is not re-run;
    - a single-use tool is withdrawn from the offered tools once it succeeds.
    A successful workspace mutation invalidates both, since reads made before
    it may now return something different.
    """

    # Parameters that describe the call instead of shaping its result.
    __NON_SEMANTIC_PARAMS: frozenset[str] = frozenset({"explanation"})

    def __init__(self, tools: list[ToolDefinitionDTO], sentinel: ToolDefinitionDTO):
        self.__tools: dict[str, ToolDefinitionDTO] = {t.name: t for t in tools}
        self.__sentinel: str = sentinel.name
        self.__executed: set[str] = set()
        self.__withdrawn: set[str] = set()

    def available_tools(self) -> list[ToolDefinitionDTO]:
        """Tools still worth offering to the model, in their original order."""
        return [t for name, t in self.__tools.items() if name not in self.__withdrawn]

    def is_duplicate(self, tool_call: ToolCallDTO) -> bool:
        return self.__signature(tool_call) in self.__executed

    def record(self, tool_call: ToolCallDTO, result: ToolResultDTO) -> None:
        tool = self.__tools.get(tool_call.name)
        if result.success and tool and tool.mutates_workspace:
            self.__executed.clear()
            self.__withdrawn.clear()
        self.__executed.add(self.__signature(tool_call))
        if result.success and tool and tool.single_use and tool.name != self.__sentinel:
            self.__withdrawn.add(tool.name)

    def __signature(self, tool_call: ToolCallDTO) -> str:
        parameters = {
            k: v
            for k, v in tool_call.parameters.items()
            if k not in self.__NON_SEMANTIC_PARAMS
        }
        return json.dumps([tool_call.name, parameters], sort_keys=True, default=str)
