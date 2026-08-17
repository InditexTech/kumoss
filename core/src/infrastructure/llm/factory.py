# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from litellm import Router

from src.infrastructure.llm._litellm import LiteLLMAdapter


class LLMFactory:
    def __init__(
        self,
        model_id: str,
        temperature: float,
        max_tokens: int,
        router: Router,
    ):
        self.__model_id = model_id
        self.__temperature = temperature
        self.__max_tokens = max_tokens
        self.__router = router

    def get(self) -> LiteLLMAdapter:
        return LiteLLMAdapter(
            model=self.__model_id,
            temperature=self.__temperature,
            max_tokens=self.__max_tokens,
            router=self.__router,
        )
