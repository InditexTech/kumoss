# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from collections.abc import Sequence

from src.shared.constants import PLAN_TARGET_MAX_LENGTH, PLAN_TARGETS_MAX_BYTES


def plan_targets_violation(targets: Sequence[object], limit: int) -> str | None:
    """Why ``targets`` cannot be sent to the iac sidecar's plan, or None.

    Checks ``limit`` (``services.iac.max_plan_targets``) and the
    contract's per-target and total-size caps, so an oversized list is
    caught before the sidecar would reject it. The message is written
    for the target generator model, which receives it as a tool error;
    ``targets`` is typed loosely because that model's output is
    unchecked JSON. It only ever asks for consolidation: the list must
    keep covering every change on the branch and its dependants, so a
    shorter list that drops some of them would plan an incomplete change.
    """
    if len(targets) > limit:
        return (
            f"{len(targets)} targets exceed the limit of {limit}. "
            + _CONSOLIDATE
            + " If the list cannot be consolidated, "
            + "`services.iac.max_plan_targets` must be raised."
        )
    size = 0
    for target in targets:
        if not isinstance(target, str) or not target:
            return f"Every target must be a non-empty string, got {target!r}."
        if len(target) > PLAN_TARGET_MAX_LENGTH:
            return (
                f"Target {target[:80]!r}... is {len(target)} characters long, "
                + f"above the limit of {PLAN_TARGET_MAX_LENGTH}."
            )
        size += len(target.encode())
    if size > PLAN_TARGETS_MAX_BYTES:
        return (
            f"The targets total {size} bytes, above the limit of "
            + f"{PLAN_TARGETS_MAX_BYTES}. "
            + _CONSOLIDATE
        )
    return None


_CONSOLIDATE = (
    "Replace the individual resources of a module with the module itself "
    + "(`module.<name>`), which still covers every one of them. Never drop "
    + "a target to fit: each one is a required change or dependant, and "
    + "leaving it out plans an incomplete change."
)
