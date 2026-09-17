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
