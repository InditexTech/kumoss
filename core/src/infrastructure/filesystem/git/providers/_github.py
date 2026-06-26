# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0
import httpx
import json
import asyncio

from typing import override


from src.domains.dto import PullRequestDTO
from src.domains.interfaces.git_provider_interface import IGitProvider

from src.shared.config import system_config
from src.shared.exceptions import ExceptionHandler


class GitHub(IGitProvider):
    def __init__(self):
        self.__client: httpx.AsyncClient = httpx.AsyncClient(
            headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            auth=httpx.BasicAuth(
                username=system_config.git.pat_user,
                password=system_config.git.pat_token,
            ),
            http2=True,
            http1=True,
            timeout=20,
        )

    @override
    async def create_pr(
        self,
        repository_url: str,
        head: str,
        base: str,
        title: str,
        description: str,
    ) -> PullRequestDTO:
        owner, repository = self.__parse_url(repository_url)
        try:
            response = await self.__client.post(
                url=f"https://api.github.com/repos/{owner}/{repository}/pulls",
                content=json.dumps(
                    {
                        "title": title,
                        "head": head,
                        "base": base,
                        "body": description,
                    }
                ),
            )
            _ = response.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise ExceptionHandler(
                message=e.response.text, error_code=e.response.status_code
            )
        except httpx.TimeoutException:
            raise ExceptionHandler(message="PR creation timeout", error_code=504)

        p_response = json.loads(response.content)
        return PullRequestDTO(
            id=p_response["number"],
            url=p_response["html_url"],
            status=p_response["state"],
        )

    @override
    async def complete_pr(self, repository_url: str, id: int) -> None:
        owner, repository = self.__parse_url(repository_url)
        try:
            await self.__poll_readiness(owner, repository, id)
            merge = await self.__client.put(
                url=f"https://api.github.com/repos/{owner}/{repository}/pulls/{id}/merge",
            )
            _ = merge.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise ExceptionHandler(
                message=e.response.text, error_code=e.response.status_code
            )
        except httpx.TimeoutException:
            raise ExceptionHandler(message="Complete PR timeout", error_code=504)

    def __parse_url(self, repository_url: str) -> tuple[str, str]:
        repository_url = repository_url.lower()
        if repository_url.find("https://") != -1:
            repository_url = repository_url[len("https://") :]
        parts = repository_url.split("/")
        if len(parts) < 3 or parts[0] != "github.com":
            raise ExceptionHandler(
                message=f"Malformed repository URL '{repository_url}'",
                error_code=400,
            )
        return parts[1], parts[2].rstrip("/").removesuffix(".git")

    async def __poll_readiness(self, owner: str, repository: str, id: int) -> None:
        async def is_ready() -> bool:
            readiness = await self.__client.get(
                url=f"https://api.github.com/repos/{owner}/{repository}/pulls/{id}",
            )
            _ = readiness.raise_for_status()
            readiness = json.loads(readiness.content)
            mergeable = readiness["mergeable"]
            if mergeable is False:
                raise ExceptionHandler(
                    message=f"Pull Request {id} cannot be merged.",
                    error_code=400,
                )
            return mergeable is True

        i = 0
        while not await is_ready():
            if i >= system_config.orchestration.pull_request_readiness_seconds:
                raise ExceptionHandler(
                    message=f"Pull Request {id} readiness polling exhausted.",
                    error_code=504,
                )
            i += 1
            await asyncio.sleep(1)
