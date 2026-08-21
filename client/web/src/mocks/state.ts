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
): StatusEntry {
  return { status, message, created_at: NOW };
}

export function makeRound(overrides: Partial<RoundDetail> = {}): RoundDetail {
  return {
    id: nextRoundId++,
    number: 1,
    statuses: [makeStatus("started"), makeStatus("completed")],
    report: null,
    plan: null,
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
    statuses: [makeStatus("started"), makeStatus("completed")],
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
  updateStatus(uuid: string, status: SessionStatus, message?: string) {
    const detail = sessions.get(uuid);
    if (!detail) return;
    const entry = makeStatus(status, message ?? null);
    detail.current_status = status;
    detail.statuses = [...detail.statuses, entry];
    const round = detail.rounds[detail.rounds.length - 1];
    if (round) round.statuses = [...round.statuses, entry];
  },
};
