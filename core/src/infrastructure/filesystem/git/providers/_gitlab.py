# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0
import httpx
import json

from typing import override
from urllib.parse import quote


from src.domains.dto import PullRequestDTO
from src.domains.interfaces.git_provider_interface import IGitProvider
from src.shared.config import system_config
from src.shared.exceptions import ExceptionHandler


class GitLab(IGitProvider):
    def __init__(self):
        self.__client: httpx.AsyncClient = httpx.AsyncClient(
            headers={
                "PRIVATE-TOKEN": system_config.git.pat_token,
                "Accept": "application/json",
            },
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
        project_id = self.__project_id(repository_url)
        try:
            response = await self.__client.post(
                url=f"https://gitlab.com/api/v4/projects/{project_id}/merge_requests",
                content=json.dumps(
                    {
                        "source_branch": head,
                        "target_branch": base,
                        "title": title,
                        "description": description,
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
            id=p_response["iid"],
            url=p_response["web_url"],
            status=p_response["state"],
        )

    @override
    async def complete_pr(self, repository_url: str, id: int) -> None:
        project_id = self.__project_id(repository_url)
        try:
            approve = await self.__client.post(
                url=(
                    f"https://gitlab.com/api/v4/projects/{project_id}"
                    f"/merge_requests/{id}/approve"
                ),
            )
            _ = approve.raise_for_status()
            response = await self.__client.put(
                url=(
                    f"https://gitlab.com/api/v4/projects/{project_id}"
                    f"/merge_requests/{id}/merge"
                ),
            )
            _ = response.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise ExceptionHandler(
                message=e.response.text, error_code=e.response.status_code
            )
        except httpx.TimeoutException:
            raise ExceptionHandler(message="Complete PR timeout", error_code=504)

    def __project_id(self, repository_url: str) -> str:
        namespace, project = self.__parse_url(repository_url)
        return quote(f"{namespace}/{project}", safe="")

    def __parse_url(self, repository_url: str) -> tuple[str, str]:
        repository_url = repository_url.lower()
        if repository_url.find("https://") != -1:
            repository_url = repository_url[len("https://") :]
        repository_url = repository_url.rstrip("/")
        parts = repository_url.split("/")
        if len(parts) != 3 or parts[0] != "gitlab.com":
            raise ExceptionHandler(
                message=f"Malformed repository URL '{repository_url}'",
                error_code=400,
            )
        return parts[1], parts[2].removesuffix(".git")
