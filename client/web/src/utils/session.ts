// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import type { Session } from "@/types/ui";

/**
 * True for a drift-remediation session, full or partial.
 *
 * Gate session-type behaviour on this, never on `useMode()`: `ModeContext` is
 * unpersisted `useState` seeded with `MODE.GENERATE`, so a refreshed or
 * deep-linked drift session reports `generate`. `session.operation` is
 * rehydrated from the backend by `buildSessionPatch`. The API has no
 * `partial_drift` operation — both drift modes arrive as `"drift"`.
 */
export function isDriftSession(session: Session): boolean {
  return session.operation === "drift";
}

/** True for an import session, full or partial (both arrive as `"import"`). */
export function isImportSession(session: Session): boolean {
  return session.operation === "import";
}

/**
 * True when merging the session's PR ends the flow and nothing is applied
 * afterwards: drift is remediated by the merge itself, and an import has
 * already written the resources into Terraform state.
 */
export function isMergeOnlySession(session: Session): boolean {
  return isDriftSession(session) || isImportSession(session);
}
