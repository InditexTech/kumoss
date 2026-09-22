// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

/**
 * Browser-only seeding.
 *
 * The store is deliberately empty under Vitest — `onUnhandledRequest:
 * "error"` plus an empty list is what lets a test assert on exactly the
 * sessions it added. Only the Service Worker entry calls this, so the
 * dev browser gets a populated sessions table and working deep links
 * without any test ever seeing the fixtures.
 */

import { buildReproSessions, buildSeedSessions } from "./data";
import { mockState } from "./state";

export function seedMockData(): void {
  for (const session of buildSeedSessions()) {
    mockState.addSession(session);
  }
}

/**
 * Broken-on-purpose sessions for the session-recovery findings.
 *
 * Kept out of `seedMockData` on purpose: `mocks.test.ts` seeds in
 * `beforeEach` and asserts the list total against
 * `buildSeedSessions().length`, and more generally a test should declare
 * exactly the world it needs. A test that wants one of these adds it
 * itself via `buildReproSessions()`.
 */
export function seedReproData(): void {
  for (const session of buildReproSessions()) {
    mockState.addSession(session);
  }
}
