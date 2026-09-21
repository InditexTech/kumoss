// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import type {
  RoundDetail,
  SessionDetail,
  SessionStatus,
  StatusEntry,
} from "@/types/api";

const NOW = "2026-01-01T00:00:00Z";

let nextRoundId = 1;

export function makeStatus(
  status: SessionStatus,
  message: string | null = null,
  createdAt: string = NOW,
): StatusEntry {
  return { status, message, created_at: createdAt };
}

/**
 * The session's last status, across every round.
 *
 * Mirrors `core`'s `DatabaseService.get_last_status(session_id)`, which
 * `api/v1/events.py` polls — deliberately *not* the last round's last
 * status, which is what `resolveSessionOutcome` reads. The two disagree
 * in the windows the REPRO fixtures model, and collapsing them would
 * stop those fixtures reproducing anything.
 *
 * Byte-identical to the removed `SessionDetail.statuses` tail: rounds are
 * ordered and a statusless round contributes nothing to the flatten.
 */
export function lastSessionStatus(
  detail: SessionDetail,
): StatusEntry | undefined {
  const statuses = detail.rounds.flatMap((r) => r.statuses);
  return statuses[statuses.length - 1];
}

export function makeRound(overrides: Partial<RoundDetail> = {}): RoundDetail {
  return {
    id: nextRoundId++,
    number: 1,
    query: "deploy a VM",
    statuses: [makeStatus("started"), makeStatus("completed")],
    reports: [],
    plans: [],
    code_changes: [],
    pull_requests: [],
    created_at: NOW,
    ...overrides,
  };
}

export function makeSessionDetail(
  overrides: Partial<SessionDetail> = {},
): SessionDetail {
  return {
    uuid: "sess-1",
    username: "user@test.com",
    operation: "generate",
    provider: "azure",
    first_query: "deploy a VM",
    workspace_uri: "https://dev.azure.com/org/project/_git/repo",
    current_status: "completed",
    in_flight: false,
    is_blocked: false,
    created_at: NOW,
    updated_at: NOW,
    workspace: {
      uri: "https://dev.azure.com/org/project/_git/repo",
      branch: "nebula/sess-1",
      root_path: "environments/dev",
    },
    scope_id: "sub-123",
    rounds: [makeRound()],
    history: [{ user: "deploy a VM", assistant: "Here is your VM" }],
    ...overrides,
  };
}

// ─── In-memory session store the handlers read from ────────────

const sessions = new Map<string, SessionDetail>();

export const mockState = {
  clear() {
    sessions.clear();
  },
  addSession(detail: SessionDetail): SessionDetail {
    sessions.set(detail.uuid, detail);
    return detail;
  },
  getSession(uuid: string): SessionDetail | undefined {
    return sessions.get(uuid);
  },
  listSessions(): SessionDetail[] {
    return [...sessions.values()];
  },
  updateStatus(
    uuid: string,
    status: SessionStatus,
    message?: string,
    createdAt?: string,
  ) {
    const detail = sessions.get(uuid);
    if (!detail) return;
    const entry = makeStatus(status, message ?? null, createdAt);
    detail.current_status = status;
    const round = detail.rounds[detail.rounds.length - 1];
    if (round) round.statuses = [...round.statuses, entry];
  },
  /**
   * Open the round an IaC call is about to run. The round starts silent
   * — no statuses, no artifacts — because the backend writes neither
   * synchronously; the SSE run fills it in as it streams.
   */
  appendRound(
    uuid: string,
    overrides: Partial<RoundDetail> = {},
  ): RoundDetail | undefined {
    const detail = sessions.get(uuid);
    if (!detail) return undefined;
    const round = makeRound({
      number: detail.rounds.length + 1,
      statuses: [],
      ...overrides,
    });
    detail.rounds = [...detail.rounds, round];
    return round;
  },
  /** Attach the artifacts a finished round produced. */
  patchRound(uuid: string, roundId: number, patch: Partial<RoundDetail>) {
    const detail = sessions.get(uuid);
    if (!detail) return;
    detail.rounds = detail.rounds.map((round) =>
      round.id === roundId ? { ...round, ...patch } : round,
    );
  },
};
