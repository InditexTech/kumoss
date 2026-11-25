# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from typing import Literal

import httpx

from src.infrastructure.exceptions import PromptFetchError
from src.infrastructure.templates._langfuse_prompts import (
    LangfusePrompts,
    default_client,
)
from src.infrastructure.templates._seed_loader import prompt_name as langfuse_name
from src.shared.constants import Environment


class _PromptFetcher:
    def __init__(self, prompts: LangfusePrompts | None = None):
        self.__prompts = prompts or default_client()

    # Not cached: the version a label points at is read at every call, so
    # moving a label in Langfuse takes effect on the next session.
    async def fetch(
        self,
        prompt_name: str,
        # "general", or a Terraform provider type name (azurerm, google...).
        scope: str,
        type: Literal["resources", "guidelines", "compliance"],
        tag: Environment,
    ) -> str:
        """The text of the version labelled ``tag``.

        Raises:
            PromptFetchError: 404 when the prompt or the label does not
                exist (callers skip optional prompts on it), the Langfuse
                status for any other refusal, 502 for a prompt that is not
                a single text and 500 when Langfuse could not be reached.
        """
        qualified_name = langfuse_name(scope, type, prompt_name)
        try:
            version = await self.__prompts.get(qualified_name, label=tag)
        except httpx.HTTPStatusError as e:
            raise PromptFetchError(
                message=f"prompt_name={qualified_name}. {e}",
                error_code=e.response.status_code,
            ) from e
        except httpx.HTTPError as e:
            raise PromptFetchError(
                message=f"prompt_name={qualified_name}. {e}",
                error_code=500,
            ) from e
        if version is None:
            raise PromptFetchError(
                message=f"prompt_name={qualified_name}. No version labelled '{tag}'",
                error_code=404,
            )
        if version.text is None:
            raise PromptFetchError(
                message=(
                    f"prompt_name={qualified_name}. Version {version.version} is "
                    + "not a single text prompt"
                ),
                error_code=502,
            )
        return version.text


# singleton shared by every session
remote_fetcher = _PromptFetcher()
