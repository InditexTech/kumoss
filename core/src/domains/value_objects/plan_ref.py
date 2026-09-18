# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class PlanRef:
    """Value object: the identity of a plan artifact a terraform run left on disk.

    ``show`` reads this artifact back and ``apply`` executes it, so what a
    caller needs to pass around after a successful plan is the artifact's
    identity rather than a flag claiming one probably exists. ``commit``
    fingerprints the workspace as it stood when the plan was produced, and
    is sampled after the plan job returns; a holder whose fingerprint no
    longer matches is holding a stale plan.

    ``stdout`` is the plan text, carried along because a drift read
    receives nothing but this ref and its result has to report the plan
    the drift was read from. It is excluded from equality and repr so the
    ref stays a clean identity in comparisons and logs.
    """

    workspace: Path
    plan_file: str
    targets: tuple[str, ...]
    commit: str
    stdout: str = field(compare=False, repr=False)
