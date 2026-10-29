// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

/**
 * Neutral factories for the client-facing session contract, plus the
 * in-memory store `handlers.ts` serves from.
 *
 * These carry no scenario data on purpose: every default is bland, so a
 * test that cares about a field sets it explicitly, and a test that does
 * not cannot come to depend on a fixture whose shape later drifts.
 */

import type {
  AdminSessionDetail,
  RoundDetail,
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

export function makeRound(overrides: Partial<RoundDetail> = {}): RoundDetail {
  return {
    id: nextRoundId++,
    number: 1,
    query: "deploy a VM",
    statuses: [makeStatus("started"), makeStatus("completed")],
    reports: [],
    compliance_checks: [],
    plans: [],
    code_changes: [],
    pull_requests: [],
    created_at: NOW,
    ...overrides,
  };
}

export function makeSessionDetail(
  overrides: Partial<AdminSessionDetail> = {},
): AdminSessionDetail {
  return {
    uuid: "sess-1",
    username: "user@test.com",
    operation: "generate",
    provider: "azure",
    first_query: "deploy a VM",
    workspace: {
      uri: "https://dev.azure.com/org/project/_git/repo",
      branch: "kumoss/sess-1",
      root_path: "environments/dev",
    },
    current_status: "completed",
    in_flight: false,
    is_blocked: false,
    created_at: NOW,
    updated_at: NOW,
    scope_id: "sub-123",
    rounds: [makeRound()],
    chat_history: [
      {
        user: "deploy a VM",
        assistant: "Done: the plan adds one VM. Need anything else?",
      },
    ],
    history: [{ user: "deploy a VM", assistant: "<raw llm summary>" }],
    ...overrides,
  };
}

// ─── In-memory session store the handlers read from ────────────

const sessions = new Map<string, AdminSessionDetail>();

export const mockState = {
  clear() {
    sessions.clear();
  },
  addSession(detail: AdminSessionDetail): AdminSessionDetail {
    sessions.set(detail.uuid, detail);
    return detail;
  },
  getSession(uuid: string): AdminSessionDetail | undefined {
    return sessions.get(uuid);
  },
  listSessions(): AdminSessionDetail[] {
    return [...sessions.values()];
  },
};
