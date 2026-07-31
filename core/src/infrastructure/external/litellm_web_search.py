# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from src.domains.dto import LLMResponseDTO
from src.infrastructure.exceptions import WebSearchToolNoContent
from src.infrastructure.llm._litellm import LiteLLMAdapter


class LiteLLMWebSearch:
    def __init__(self, litellm: LiteLLMAdapter) -> None:
        self.__client: LiteLLMAdapter = litellm

    async def search(self, query: str) -> str:
        response_dto: LLMResponseDTO = await self.__client.inference(
            msg=query,
            system_prompt=None,
            web_search=True,
        )
        if not response_dto.text:
            raise WebSearchToolNoContent(
                message=f"Web search with query '{query}' haven't returned any content.",
                error_code=502,
            )
        return response_dto.text
