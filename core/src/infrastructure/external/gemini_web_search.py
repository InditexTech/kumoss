# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from src.domains.dto import LLMResponseDTO
from src.infrastructure.exceptions import WebSearchToolNoContent
from src.infrastructure.llm._google_gemini import GoogleGemini


class GeminiWebSearch:
    def __init__(self, gemini: GoogleGemini) -> None:
        self.__client: GoogleGemini = gemini

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
