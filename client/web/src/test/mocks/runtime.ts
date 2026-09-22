// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

/**
 * The in-flight run registry.
 *
 * An IaC POST returns 202 with only a session id; the work happens in a
 * background task and the client learns about it over SSE, then re-reads
 * the session for artifacts. To reproduce that split the POST handler
 * records a *plan* for the round here, and the SSE handler executes it —
 * writing statuses as it streams and attaching the artifacts just before
 * it emits COMPLETED. Nothing is materialised up front, so a client that
 * reads the session mid-stream sees exactly the partial aggregate the
 * backend would return.
 */

import {
  createSseEventSequence,
  getScenario,
  makeCodeChangeRef,
  makePlanRef,
  makeReportRef,
  type MockContentType,
  type SseOutcome,
  type SseStep,
} from "./data";
import { lastSessionStatus, mockState } from "./state";

export interface PendingRun {
  sessionId: string;
  roundId: number;
  roundNumber: number;
  /** Scenario whose artifacts the round will produce. */
  content: MockContentType;
  /** Wording of the generating stage: generate | drift | partial_drift | import | apply. */
  operation: string;
  outcome: SseOutcome;
  /** Failure reason / rejection rationale for a non-completed outcome. */
  message?: string;
}

const pending = new Map<string, PendingRun>();

export function schedule(run: PendingRun): void {
  pending.set(run.sessionId, run);
}

export function takePending(sessionId: string): PendingRun | undefined {
  const run = pending.get(sessionId);
  pending.delete(sessionId);
  return run;
}

export function clearRuns(): void {
  pending.clear();
}

/** The SSE frames a pending run will emit, in order. */
export function runSequence(run: PendingRun): SseStep[] {
  return createSseEventSequence(run.operation, run.outcome, run.message);
}

/**
 * Mirror one streamed frame into the session store, so a concurrent
 * GET /sessions/{id} agrees with what the stream has said so far.
 */
export function applyStep(run: PendingRun, step: SseStep): void {
  const status = step.data.status_msg.toLowerCase() as Parameters<
    typeof mockState.updateStatus
  >[1];

  // A duplicate frame is the 5s poll re-reading the *same* status row —
  // it must not append a second one, or the timeline shows the stage
  // twice. A retry (GENERATING after VALIDATING) is a real transition
  // and does get its own row.
  const detail = mockState.getSession(run.sessionId);
  const last = detail ? lastSessionStatus(detail) : undefined;
  if (last?.status === status) return;

  mockState.updateStatus(
    run.sessionId,
    status,
    step.data.detail.message,
    new Date().toISOString(),
  );
}

/**
 * Upload the round's artifacts. Called once, immediately before the
 * COMPLETED frame — the backend writes them during the REPORT stage,
 * which is why the client only re-reads the session after a terminal
 * event.
 */
export function materializeArtifacts(run: PendingRun): void {
  const scenario = getScenario(run.content);
  const now = new Date().toISOString();
  const isApply = run.operation === "apply";

  mockState.patchRound(run.sessionId, run.roundId, {
    reports: [
      makeReportRef(
        run.sessionId,
        run.roundNumber,
        scenario.reportType,
        scenario.report,
        now,
      ),
    ],
    plans: isApply
      ? []
      : [
          makePlanRef(
            run.sessionId,
            run.roundNumber,
            scenario.plan,
            scenario.targets,
            now,
            scenario.reportType === "drift",
          ),
        ],
    code_changes: isApply
      ? []
      : scenario.files.map((file) =>
          makeCodeChangeRef(
            run.sessionId,
            run.roundNumber,
            file.name,
            file.content,
            now,
          ),
        ),
  });

  const detail = mockState.getSession(run.sessionId);
  const round = detail?.rounds.find((r) => r.id === run.roundId);
  if (detail && round) {
    detail.history = [
      ...(detail.history ?? []),
      { user: round.query, assistant: scenario.history[0].assistant },
    ];
  }
}
