# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""LiteLLM Router completions, ported from the core's ``LiteLLMAdapter``.

The core still builds the request (history formatting, tool schemas,
the thinking / temperature switch) and interprets the reply (stop-reason
mapping, tool-argument parsing, whether to keep the reasoning text).
This module owns only what needs LiteLLM: the one
``router.acompletion(**kwargs, drop_params=True)`` call, the
``OpenAIError`` translation, and the raw fields the core reads off the
``ModelResponse`` — byte-for-byte the expressions the adapter used.

It also resolves the model's provider with ``litellm.get_llm_provider``
the way the core's Phoenix tracer did (``_llm_model_name_attributes``),
since the core no longer has LiteLLM to ask.
"""

from __future__ import annotations

from typing import Any, cast

import litellm
from litellm import ModelResponse, Usage
from litellm.router import Router
from openai import OpenAIError

from .exceptions import InferenceCallAPIError
from .logger import logging
from .models import CompletionResponse, ToolCall


def model_name_and_provider(model: str) -> tuple[str | None, str | None]:
    """``litellm.get_llm_provider(model)``'s first two fields, or nulls.

    Mirrors the core tracer's ``_llm_model_name_attributes``: any
    exception means "unresolvable" (a ``model_list`` alias, say), which
    the tracer answered by falling back to the raw model string.
    """
    try:
        model_name, llm_provider, *_ = litellm.get_llm_provider(model)
    except Exception:
        return None, None
    return model_name, llm_provider


class CompletionService:
    def __init__(self, router: Router) -> None:
        self.__router = router

    async def complete(self, kwargs: dict[str, Any]) -> CompletionResponse:
        """Run one completion with exactly ``kwargs`` (plus ``drop_params``).

        Raises ``InferenceCallAPIError`` carrying the provider status code
        on any ``OpenAIError`` (LiteLLM's exceptions subclass it), exactly
        like the adapter; anything else propagates.
        """
        model = kwargs["model"]
        try:
            response = cast(
                ModelResponse,
                await self.__router.acompletion(**kwargs, drop_params=True),
            )
        except OpenAIError as e:
            logging.error(f"LiteLLM API error: {e!r}")
            raise InferenceCallAPIError(
                message=f"Inference call to {model} failed.",
                error_code=getattr(e, "status_code", 502),
            )

        message = response.choices[0].message
        usage: Usage | None = getattr(response, "usage", None)
        model_name, llm_provider = model_name_and_provider(model)

        return CompletionResponse(
            text=message.content or "",
            finish_reason=response.choices[0].finish_reason,
            model=response.model,
            prompt_tokens=usage.prompt_tokens if usage else 0,
            completion_tokens=usage.completion_tokens if usage else 0,
            tool_calls=[
                ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=tc.function.arguments,
                )
                for tc in (message.tool_calls or [])
            ],
            reasoning_content=getattr(message, "reasoning_content", None),
            model_name=model_name,
            llm_provider=llm_provider,
        )
