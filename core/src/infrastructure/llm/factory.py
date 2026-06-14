# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from src.infrastructure.llm._google_gemini import GoogleGemini
from src.infrastructure.llm._anthropic_vertex import AnthropicVertex
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
        if provider.value["provider"] in ["google", "anthropicVertex"]:
            creds_path = system_config.llm.google_application_credentials
            sa_secret = system_config.llm.google_sa_secret
            if creds_path and sa_secret:
                with open(creds_path, "w") as f:
                    _ = f.write(sa_secret)

    def get(self):
        match self.__provider.value["provider"]:
            case "anthropicVertex":
                return AnthropicVertex(
                    model=self.__provider,
                    api_id=system_config.llm.google_vertex_project,
                    temperature=self.__temperature,
                )
            case "google":
                return GoogleGemini(
                    model=self.__provider,
                    api_id=system_config.llm.google_vertex_project,
                    temperature=self.__temperature,
                )
            case _:
                raise ValueError(f"Unsupported LLM {self.__provider.value['provider']}")
