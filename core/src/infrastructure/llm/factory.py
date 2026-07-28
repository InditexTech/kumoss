# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from src.infrastructure.llm._litellm import LiteLLMAdapter
from src.shared.config import system_config
from src.shared.constants import LLMProvider


class LLMFactory:
    def __init__(
        self,
        provider: LLMProvider,
        temperature: float,
    ):
        self.__provider = provider
        self.__temperature = temperature

    def _get_provider_kwargs(self) -> dict:
        model_id = self.__provider.value["model_id"]
        provider_kwargs = system_config.llm.get_provider_credentials(model_id)
        if region := self.__provider.value.get(
            "region"
        ):  # Prioritize region from LLMProvider enum if available
            provider_kwargs["vertex_location"] = region
        return provider_kwargs

    def get(self):
        return LiteLLMAdapter(
            model=self.__provider,
            temperature=self.__temperature,
            provider_kwargs=self._get_provider_kwargs(),
        )
