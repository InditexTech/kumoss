# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import Any

from src.domains.dto import PolicyDecision


class IPolicyEngine(ABC):
    """Evaluates the compliance policy against a plan.

    Deterministic counterpart of the LLM compliance audit: the same plan
    gives the same decision. The policy itself lives outside the engine
    (a Langfuse prompt), so an operator can change it without a release.
    """

    @abstractmethod
    async def evaluate(
        self, plan_json: dict[str, Any], providers: Sequence[str]
    ) -> PolicyDecision:
        """The policy's decision on ``plan_json``, the parsed ``show -json``
        of a plan whose root module uses ``providers``.

        Raises:
            PolicyEvaluationError: the policy could not be evaluated.
        """

    @abstractmethod
    async def verify(self, providers: Sequence[str]) -> None:
        """Check that the engine and the current policies work, the general
        one and those of ``providers``, by evaluating them against an empty
        plan.

        Raises:
            PolicyEvaluationError: they do not.
        """
