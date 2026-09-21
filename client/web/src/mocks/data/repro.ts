// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

/**
 * Reproduction fixtures for the session-recovery review findings.
 *
 * These are deliberately *broken* sessions, kept apart from
 * `SESSION_SPECS` so the happy-path demo stays clean and so the whole
 * set can be deleted in one go once the findings are fixed. Every one
 * of them carries its finding number in the UUID (`...-90NN-...b00N`),
 * the repo name, the branch and the query text, so whatever the UI does
 * is traceable to the fixture that caused it without opening devtools.
 *
 * What makes them reproduce anything is a fidelity detail the mocks
 * already had: `handlers/events.ts` answers a no-pending-run stream
 * from `lastSessionStatus(detail)` — the *session's* last status, the
 * flatten across every round — exactly as
 * `core/src/api/v1/events.py` does via
 * `DatabaseService.get_last_status(session_id)`. `resolveSessionOutcome`
 * instead reads the *last round's* last status. The two agree except in
 * the windows modelled below, which is the whole bug surface.
 *
 * See `src/mocks/README.md` → "Reproduction fixtures".
 */

import { buildSession, MOCK_USER_EMAIL, type SessionSpec } from "./sessions";
import type { SessionDetail } from "@/types/api";

const REPO_REPRO = "https://github.com/contoso/nebula-repro";

/** Findings get their own id block so they never collide with the seeds. */
export const REPRO_IDS = {
  /** Finding 1 — statusless round ⇒ false "Pipeline completed" + flap. */
  flap: "5f2c1a80-9001-4b7e-9c31-a1b2c3d4b001",
  /** Finding 2 — orphaned runner, lock stuck true ⇒ endless spinner. */
  orphanLocked: "5f2c1a80-9002-4b7e-9c31-a1b2c3d4b002",
  /** Finding 2 control — same status, lock released. */
  orphanUnlocked: "5f2c1a80-9003-4b7e-9c31-a1b2c3d4b003",
  /** Finding 3 — the in-progress session you navigate away *from*. */
  latchFrom: "5f2c1a80-9004-4b7e-9c31-a1b2c3d4b004",
  /** Finding 3 — the finished session you navigate *to*. */
  latchTo: "5f2c1a80-9005-4b7e-9c31-a1b2c3d4b005",
} as const;

export const REPRO_SPECS: SessionSpec[] = [
  // ─── Finding 1 ──────────────────────────────────────────────
  // Round 2 exists with zero statuses: the row is INSERTed before the
  // runner writes `started`. So the session's last status is round 1's
  // `completed` (what the stream replays) while the last *round* has no
  // status at all (what the resolver sees → "in-progress").
  //
  // The session therefore reads "completed" in the table and flaps when
  // opened. `stoppedAt: 0` is what holds the window open indefinitely;
  // in production it lasts one DB round trip.
  {
    uuid: REPRO_IDS.flap,
    username: MOCK_USER_EMAIL,
    operation: "generate",
    provider: "azure",
    workspace_uri: REPO_REPRO,
    branch: "nebula/repro-1-statusless-round",
    root_path: "environments/repro-1",
    scope_id: "sub-repro-0001",
    age: 0.2,
    // The lock is held — the runner for round 2 acquired it and is
    // about to write its first status.
    in_flight: true,
    rounds: [
      {
        content: "generate",
        query:
          "REPRO-1 statusless round: this session reports completed but flaps between planning and results when opened",
        outcome: "completed",
      },
      {
        content: "generate_multi",
        query: "REPRO-1 iteration whose round row exists with no statuses yet",
        outcome: "running",
        stoppedAt: 0,
      },
    ],
  },

  // ─── Finding 2 ──────────────────────────────────────────────
  // The runner's process died between `acquire_in_flight` and its
  // `finally`, so the lock never cleared and no terminal status was ever
  // written. Nothing server-side reaps this: `mark_failed` only runs
  // inside a live runner's `except`, and there is no startup sweep.
  //
  // This is the fixture that shows an `in_flight` gate cannot fix the
  // finding — the flag is *true* here, so the gate passes and the
  // spinner runs anyway.
  {
    uuid: REPRO_IDS.orphanLocked,
    username: MOCK_USER_EMAIL,
    operation: "generate",
    provider: "azure",
    workspace_uri: REPO_REPRO,
    branch: "nebula/repro-2-orphaned-locked",
    root_path: "environments/repro-2",
    scope_id: "sub-repro-0002",
    age: 26,
    in_flight: true,
    rounds: [
      {
        content: "generate",
        query:
          "REPRO-2 orphaned run, lock stuck true: pod died mid-generation 26h ago, spinner never resolves and no error is shown",
        outcome: "running",
        stoppedAt: 3, // started, filtering, generating — never terminal
      },
    ],
  },

  // Control for finding 2: same resting status, lock released. This is
  // the *only* shape an `in_flight === true` gate would catch, which is
  // why that gate is the wrong fix — compare the two side by side.
  //
  // Being a drift round, its ladder carries `reconciling` before
  // `generating`, so `stoppedAt` is one further along than REPRO-2's to
  // rest on the same status. What the control holds fixed is that
  // status, not the stage count.
  {
    uuid: REPRO_IDS.orphanUnlocked,
    username: MOCK_USER_EMAIL,
    operation: "drift",
    provider: "azure",
    workspace_uri: REPO_REPRO,
    branch: "nebula/repro-2b-orphaned-unlocked",
    root_path: "environments/repro-2b",
    scope_id: "sub-repro-0002",
    age: 30,
    in_flight: false,
    rounds: [
      {
        content: "drift",
        query:
          "REPRO-2b orphaned run, lock released: same non-terminal status as REPRO-2 but in_flight is false",
        outcome: "running",
        stoppedAt: 4, // started, filtering, reconciling, generating
      },
    ],
  },

  // ─── Finding 3 ──────────────────────────────────────────────
  // `useSessionLoader` never calls `setInProgress(null)`, so a single
  // hook instance that sees an in-progress session and then a finished
  // one keeps the stale resume target and renders the still-running
  // placeholder over a session that has results.
  //
  // Reaching this needs a `results/:A` → `results/:B` transition with no
  // remount, which today's UI has no affordance for — see the README.
  // The pair exists so the behaviour is one nav call away from visible.
  {
    uuid: REPRO_IDS.latchFrom,
    username: MOCK_USER_EMAIL,
    operation: "generate",
    provider: "azure",
    workspace_uri: REPO_REPRO,
    branch: "nebula/repro-3-latch-from",
    root_path: "environments/repro-3",
    scope_id: "sub-repro-0003",
    age: 1,
    in_flight: true,
    rounds: [
      {
        content: "generate",
        query:
          "REPRO-3a latch source (in progress): navigate from this session's results URL to REPRO-3b without remounting",
        outcome: "running",
        stoppedAt: 2,
      },
    ],
  },
  {
    uuid: REPRO_IDS.latchTo,
    username: MOCK_USER_EMAIL,
    operation: "generate",
    provider: "azure",
    workspace_uri: REPO_REPRO,
    branch: "nebula/repro-3-latch-to",
    root_path: "environments/repro-3",
    scope_id: "sub-repro-0003",
    age: 1.5,
    rounds: [
      {
        content: "generate_multi",
        query:
          "REPRO-3b latch target (completed with artifacts): should show results, would show the running placeholder if inProgress latched",
        outcome: "completed",
      },
    ],
  },
];

export function buildReproSessions(): SessionDetail[] {
  return REPRO_SPECS.map(buildSession);
}
