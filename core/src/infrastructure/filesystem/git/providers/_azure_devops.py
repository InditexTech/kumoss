# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0
import httpx
import json

from typing import override


from src.domains.dto import PullRequestDTO
from src.domains.interfaces.git_provider_interface import IGitProvider

from src.shared.config import system_config
from src.shared.exceptions import ExceptionHandler


_API_VERSION = "7.1-preview"


class AzureDevOps(IGitProvider):
    def __init__(self):
        self.__client: httpx.AsyncClient = httpx.AsyncClient(
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            # ADO accepts any value in the username slot; the PAT goes in the
            # password slot.
            auth=httpx.BasicAuth(
                username="",
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
        org, project, repository = self.__parse_url(repository_url)
        try:
            response = await self.__client.post(
                url=(
                    f"https://dev.azure.com/{org}/{project}/_apis/git/"
                    f"repositories/{repository}/pullrequests?api-version={_API_VERSION}"
                ),
                content=json.dumps(
                    {
                        "sourceRefName": f"refs/heads/{head}",
                        "targetRefName": f"refs/heads/{base}",
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
            id=p_response["pullRequestId"],
            url=p_response["url"],
            status=p_response["status"],
        )

    @override
    async def complete_pr(self, repository_url: str, id: int) -> None:
        org, project, repository = self.__parse_url(repository_url)
        try:
            conn = await self.__client.get(
                url=(
                    f"https://dev.azure.com/{org}/_apis/connectionData"
                    f"?api-version={_API_VERSION}"
                ),
            )
            _ = conn.raise_for_status()
            user_id = json.loads(conn.content)["authenticatedUser"]["id"]

            approve = await self.__client.put(
                url=(
                    f"https://dev.azure.com/{org}/{project}/_apis/git/"
                    f"repositories/{repository}/pullrequests/{id}/reviewers/{user_id}"
                    f"?api-version={_API_VERSION}"
                ),
                content=json.dumps({"vote": 10, "id": user_id}),
            )
            _ = approve.raise_for_status()

            pr_get = await self.__client.get(
                url=(
                    f"https://dev.azure.com/{org}/{project}/_apis/git/"
                    f"repositories/{repository}/pullrequests/{id}"
                    f"?api-version={_API_VERSION}"
                ),
            )
            _ = pr_get.raise_for_status()
            commit_id = json.loads(pr_get.content)["lastMergeSourceCommit"]["commitId"]

            patch = await self.__client.patch(
                url=(
                    f"https://dev.azure.com/{org}/{project}/_apis/git/"
                    f"repositories/{repository}/pullrequests/{id}"
                    f"?api-version={_API_VERSION}"
                ),
                content=json.dumps(
                    {
                        "status": "completed",
                        "lastMergeSourceCommit": {"commitId": commit_id},
                    }
                ),
            )
            _ = patch.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise ExceptionHandler(
                message=e.response.text, error_code=e.response.status_code
            )
        except httpx.TimeoutException:
            raise ExceptionHandler(message="Complete PR timeout", error_code=504)

    def __parse_url(self, repository_url: str) -> tuple[str, str, str]:
        repository_url = repository_url.lower()
        if repository_url.find("https://") != -1:
            repository_url = repository_url[len("https://") :]
        repository_url = repository_url.rstrip("/")
        parts = repository_url.split("/")
        if (
            len(parts) != 5
            or parts[0].find("dev.azure.com") == -1
            or parts[3] != "_git"
        ):
            raise ExceptionHandler(
                message=f"Malformed repository URL '{repository_url}'",
                error_code=400,
            )
        return parts[1], parts[2], parts[4].removesuffix(".git")
