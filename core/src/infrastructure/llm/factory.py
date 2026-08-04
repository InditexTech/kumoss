# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from src.infrastructure.llm._litellm import LiteLLMAdapter
from src.shared.config import system_config


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

    def _get_provider_kwargs(self) -> dict:
        provider_kwargs = system_config.llm.get_provider_credentials(self.__model_id)
        return provider_kwargs

    def get(self):
        return LiteLLMAdapter(
            model=self.__model_id,
            temperature=self.__temperature,
            max_tokens=self.__max_tokens,
            provider_kwargs=self._get_provider_kwargs(),
        )
