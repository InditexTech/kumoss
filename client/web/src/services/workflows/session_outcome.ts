// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

/**
 * WORKFLOW: Session Outcome
 *
 * Results are not carried by SSE events; a finished round must be
 * reconstructed from GET /sessions/{id} plus its presigned artifact
 * URLs. This module is the single place that does it — for live runs
 * (round-terminal SSE event), deep links / refresh, and the sessions
 * table "Reload Session" action.
 */

import {
  getSessionDetail,
  fetchArtifactContent,
} from "@/services/core/sessions";
import { composeFileArtifacts } from "@/utils/diffUtils";
import { normalizeHistory } from "@/types/api";
import type { HistoryEntry, CodeChangeRef, RoundDetail, SessionDetail } from "@/types/api";
import type { TerraformReport, PlanSummary } from "@/types";
import type { ApplyResultsData, Session } from "@/types/ui";

// ─── Outcome model ─────────────────────────────────────────────

export type SessionOutcome =
  | {
      kind: "results";
      detail: SessionDetail;
      round: RoundDetail;
      report: TerraformReport | null;
      code: string;
      targets: string[] | undefined;
    }
  | {
      kind: "apply-results";
      detail: SessionDetail;
      round: RoundDetail;
      report: TerraformReport | null;
    }
  | {
      kind: "rejected";
      detail: SessionDetail;
      rationale: string;
      /** Artifacts of the most recent round that produced any, when the
       *  rejection is an iteration on a session with earlier results —
       *  keeps the split result panel across deep links / refreshes. */
      prior?: RoundArtifacts;
    }
  | { kind: "failed"; detail: SessionDetail | null; message: string };

/** Apply rounds are detected by their "apply" status; the session's
 *  `operation` keeps the original generate/drift/import value. */
export function isApplyRound(round: RoundDetail): boolean {
  return round.statuses.some((s) => s.status === "apply");
}

export function extractProjectName(workspaceUri: string): string {
  const segments = workspaceUri.replace(/\/+$/, "").split("/");
  return segments[segments.length - 1] || workspaceUri;
}

// ─── Waiting for a new round (stale-terminal guard) ────────────
// Iteration/apply calls write no status synchronously: the 202 returns
// before the background runner creates the new round, so subscribing
// immediately would replay the PREVIOUS round's terminal status.

const NEW_ROUND_POLL_MS = 4_000;
const NEW_ROUND_TIMEOUT_MS = 5 * 60_000;

function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    const timer = setTimeout(resolve, ms);
    signal?.addEventListener(
      "abort",
      () => {
        clearTimeout(timer);
        resolve();
      },
      { once: true },
    );
  });
}

/**
 * Poll the session until a round beyond `baselineRounds` exists and has
 * written its first status. Throws on timeout or abort.
 */
export async function waitForNewRound(
  sessionId: string,
  baselineRounds: number,
  signal?: AbortSignal,
): Promise<void> {
  const deadline = Date.now() + NEW_ROUND_TIMEOUT_MS;
  while (Date.now() < deadline) {
    if (signal?.aborted) throw new DOMException("Aborted", "AbortError");
    const detail = await getSessionDetail(sessionId);
    const latest = detail.rounds[detail.rounds.length - 1];
    if (
      detail.rounds.length > baselineRounds &&
      latest &&
      latest.statuses.length > 0
    ) {
      return;
    }
    await sleep(NEW_ROUND_POLL_MS, signal);
  }
  if (signal?.aborted) throw new DOMException("Aborted", "AbortError");
  throw new Error("Timed out waiting for the new round to start");
}

// ─── Outcome resolution ────────────────────────────────────────

export interface RoundArtifacts {
  report: TerraformReport | null;
  code: string;
  targets: string[] | undefined;
}

/**
 * Every code-change artifact across the given rounds, grouped per file
 * in emission order. A round only carries the files it touched, so the
 * session's full file set must be merged across rounds. All artifacts of
 * a file are kept: a session can touch the same file several times and
 * updated-file artifacts are sequential diffs, so the whole group is
 * needed to reconstruct the cumulative change (see composeFileArtifacts).
 */
function collectCodeChanges(
  rounds: RoundDetail[],
): [string, CodeChangeRef[]][] {
  const byName = new Map<string, CodeChangeRef[]>();
  for (const round of rounds) {
    for (const change of round.code_changes) {
      const group = byName.get(change.file_name);
      if (group) {
        group.push(change);
      } else {
        byName.set(change.file_name, [change]);
      }
    }
  }
  return [...byName.entries()];
}

async function fetchRoundArtifacts(
  round: RoundDetail,
  rounds: RoundDetail[],
): Promise<RoundArtifacts> {
  const codeChanges = collectCodeChanges(rounds);
  const [reportContent, planContent, ...fileContents] = await Promise.all([
    round.report
      ? fetchArtifactContent(round.report.url)
      : Promise.resolve(null),
    round.plan ? fetchArtifactContent(round.plan.url) : Promise.resolve(null),
    ...codeChanges.map(async ([fileName, changes]) => {
      const contents = await Promise.all(
        changes.map((c) => fetchArtifactContent(c.url)),
      );
      return composeFileArtifacts(fileName, contents);
    }),
  ]);

  let report: TerraformReport | null = null;
  if (reportContent) {
    try {
      report = JSON.parse(reportContent);
    } catch {
      // ignore malformed report
    }
  }

  const parts: string[] = [];
  if (planContent) {
    parts.push(`<Terraform_Plan>\n${planContent}\n</Terraform_Plan>`);
  }
  codeChanges.forEach(([fileName], i) => {
    parts.push(`<${fileName}>\n${fileContents[i]}\n</${fileName}>`);
  });

  return { report, code: parts.join("\n"), targets: round.plan?.targets };
}

/**
 * Reconstruct the latest round's outcome from the session detail and its
 * artifacts. Accepts a session id (fetched with history for chat rebuild)
 * or an already-fetched detail. Artifact fetches get one detail-refetch
 * retry: presigned URLs outlive the cached detail's 24h TTL, so a stale
 * URL (403) is fixed by re-reading the session.
 */
export async function resolveSessionOutcome(
  source: string | SessionDetail,
): Promise<SessionOutcome> {
  let detail =
    typeof source === "string"
      ? await getSessionDetail(source, { includeHistory: true })
      : source;

  let round = detail.rounds[detail.rounds.length - 1];
  if (!round) {
    return { kind: "failed", detail, message: "Session has no rounds" };
  }

  const lastStatus = round.statuses[round.statuses.length - 1];
  if (lastStatus?.status === "failed") {
    return {
      kind: "failed",
      detail,
      message: lastStatus.message || "Process failed",
    };
  }
  if (lastStatus?.status === "uncompleted") {
    // Rejected rounds produce no artifacts; the rationale is the status
    // message. A rejected iteration must keep showing the previous round's
    // result, so hydrate the most recent round that produced artifacts —
    // otherwise deep links / refreshes would lose the split result panel.
    const rationale = lastStatus.message || "The request was rejected";
    const priorRound = detail.rounds
      .slice(0, -1)
      .reverse()
      .find((r) => r.report || r.plan || r.code_changes.length > 0);
    if (!priorRound) {
      return { kind: "rejected", detail, rationale };
    }
    try {
      let prior: RoundArtifacts;
      try {
        prior = await fetchRoundArtifacts(priorRound, detail.rounds);
      } catch {
        // Same stale-presigned-URL retry as the results path below.
        const fresh = await getSessionDetail(detail.uuid, {
          includeHistory: true,
        });
        const freshRound = fresh.rounds.find((r) => r.id === priorRound.id);
        if (!freshRound) throw new Error("prior round vanished");
        prior = await fetchRoundArtifacts(freshRound, fresh.rounds);
        detail = fresh;
      }
      return { kind: "rejected", detail, rationale, prior };
    } catch {
      // Artifacts are a nice-to-have here; degrade to the chat-only view.
      return { kind: "rejected", detail, rationale };
    }
  }

  // Apply outcomes ignore code, so skip the other rounds' file fetches.
  const codeRounds = (d: SessionDetail, r: RoundDetail) =>
    isApplyRound(r) ? [r] : d.rounds;

  let artifacts: RoundArtifacts;
  try {
    artifacts = await fetchRoundArtifacts(round, codeRounds(detail, round));
  } catch {
    detail = await getSessionDetail(detail.uuid, { includeHistory: true });
    round =
      detail.rounds.find((r) => r.id === round.id) ??
      detail.rounds[detail.rounds.length - 1];
    artifacts = await fetchRoundArtifacts(round, codeRounds(detail, round));
  }

  if (isApplyRound(round)) {
    return { kind: "apply-results", detail, round, report: artifacts.report };
  }
  return { kind: "results", detail, round, ...artifacts };
}

// ─── Session-context projection ────────────────────────────────

/**
 * Map an outcome onto the UI Session shape. Callers that already hold
 * live wizard values (project from the mapper, environment from the
 * chosen iac_path) should keep them over the derived fallbacks here.
 */
export function buildSessionPatch(outcome: SessionOutcome): Partial<Session> {
  if (outcome.kind === "failed") {
    const patch: Partial<Session> = { current_status: "failed" };
    if (outcome.detail) patch.session_id = outcome.detail.uuid;
    return patch;
  }

  const { detail } = outcome;
  const patch: Partial<Session> = {
    session_id: detail.uuid,
    cloud: detail.provider,
    project: extractProjectName(detail.workspace_uri),
    environment: detail.workspace.root_path ?? undefined,
    repositoryUrl: detail.workspace.uri,
    branchName: detail.workspace.branch,
    firstQuery: detail.first_query ?? undefined,
    full_history: normalizeHistory(detail.history),
    apply_allowed: !detail.is_blocked,
    current_status: detail.current_status,
  };

  if (outcome.kind === "results") {
    patch.terraform_report = outcome.report ?? undefined;
    patch.terraform_targets = outcome.targets;
    patch.code = outcome.code;
  } else if (outcome.kind === "apply-results") {
    patch.terraform_report = outcome.report ?? undefined;
  } else if (outcome.kind === "rejected" && outcome.prior) {
    patch.terraform_report = outcome.prior.report ?? undefined;
    patch.terraform_targets = outcome.prior.targets;
    patch.code = outcome.prior.code;
  }

  return patch;
}

/**
 * Append the round's assistant summary unless the fetched history already
 * ends with it — the backend persists a rejected round's rationale into the
 * history itself, so an unconditional append would show it twice.
 */
export function appendAssistantMessage(
  history: HistoryEntry[] | undefined,
  content: string,
): HistoryEntry[] {
  const base = history ?? [];
  const last = base[base.length - 1];
  if (last?.role === "assistant" && last.content === content) return base;
  return [...base, { role: "assistant", content }];
}

/** The apply-results panel data for an apply round. */
export function buildApplyResults(
  outcome: Extract<SessionOutcome, { kind: "apply-results" }>,
): ApplyResultsData {
  return {
    sessionId: outcome.detail.uuid,
    status: outcome.report?.status ?? "Unknown",
    message: outcome.report?.execution_summary ?? "",
    errorMessage: "",
    timestamp: outcome.detail.updated_at,
    applyReport: outcome.report ?? null,
  };
}

/** The assistant chat entry summarizing what the round produced. */
export function buildAssistantMessage(outcome: SessionOutcome): string {
  switch (outcome.kind) {
    case "rejected":
      return outcome.rationale;
    case "failed":
      return outcome.message;
    case "apply-results":
      return outcome.report?.execution_summary || "Apply finished.";
    case "results": {
      const report = outcome.report;
      if (outcome.detail.operation === "drift") {
        if (typeof report?.summary === "string") return report.summary;
      }
      if (report?.potential_impact?.summary) {
        return report.potential_impact.summary;
      }
      const counts = report?.summary;
      if (counts && typeof counts === "object" && "create" in counts) {
        const c = counts as PlanSummary;
        return `Plan ready: ${c.create} to create, ${c.update} to update, ${c.delete} to delete, ${c.recreate} to recreate.`;
      }
      return "Your infrastructure changes are ready for review.";
    }
  }
}
