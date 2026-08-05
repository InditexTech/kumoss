# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from typing import Literal
# from functools import lru_cache

import httpx
from phoenix.client import AsyncClient

from src.shared.config import system_config
from src.infrastructure.exceptions import PhoenixPromptFetchError


class _PromptFetcher:
    def __init__(self):
        self.__client = AsyncClient(base_url=system_config.telemetry.collector_url)

    # @lru_cache() - we want to fetch the latest version of the tag at runtime
    async def fetch(
        self,
        prompt_name: str,
        scope: Literal["general", "azure", "gcp", "aws", "oci", "kubernetes"],
        type: Literal["resources", "guidelines"],
        tag: Literal["production", "development"],
    ) -> str:
        qualified_name = f"{scope}-{type}-{prompt_name}"
        try:
            prompt_obj = await self.__client.prompts.get(
                prompt_identifier=qualified_name,
                tag=tag,
            )
            return prompt_obj.__dict__["_template"]["messages"][0]["content"][0]["text"]
        except httpx.HTTPStatusError as e:
            raise PhoenixPromptFetchError(
                message=f"prompt_name={qualified_name}. {e.args[0]}",
                error_code=e.response.status_code,
            )
        except httpx.HTTPError as e:
            raise PhoenixPromptFetchError(
                message=f"prompt_name={qualified_name}. {e.args[0]}",
                error_code=500,
            )
        except KeyError:
            raise PhoenixPromptFetchError(
                message=f"error retrieving prompt from Phoenix API. name={qualified_name}",
                error_code=502,
            )


# singleton for caching prompts across different sessions
remote_fetcher = _PromptFetcher()

if __name__ == "__main__":
    import time

    async def main():
        prompt_fetcher = _PromptFetcher()
        tags = ["development", "development", "development", "development"]
        for i in range(len(tags)):
            start = time.time()
            prompt = await prompt_fetcher.fetch(
                prompt_name="networking",
                scope="azure",
                type="guidelines",
                tag=tags[i],
                # date=datetime.now(UTC).strftime('%Y-%m-%d') if i < 2 else "hey"
            )
            print(time.time() - start)
            print(prompt)

        print()

    import asyncio

    asyncio.run(main())
