# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from functools import cache

from litellm.router import Router

from src.infrastructure.llm._litellm import LiteLLMAdapter
from src.shared.config import system_config


# Lazily initialized singleton.
@cache
def _default_router() -> Router:
    return system_config.llm.create_router()


class LLMFactory:
    def __init__(
        self,
        model_id: str,
        temperature: float,
        max_tokens: int,
    ):
        self.__model_id = model_id
        self.__temperature = temperature
        self.__max_tokens = max_tokens

    def get(self) -> LiteLLMAdapter:
        return LiteLLMAdapter(
            model=self.__model_id,
            temperature=self.__temperature,
            max_tokens=self.__max_tokens,
            timeout=system_config.llm.timeout,
            router=_default_router(),
            web_search_model=system_config.llm.web_search_model,
        )
