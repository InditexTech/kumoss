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
  fetchArtifact,
  fetchArtifactContent,
  fetchPlanType,
} from "@/services/core/sessions";
import { composeFileArtifacts } from "@/utils/diffUtils";
import { normalizeHistory } from "@/types/api";
import type {
  HistoryEntry,
  CodeChangeRef,
  ReportRef,
  RoundDetail,
  SessionDetail,
  TerraformPlanRef,
} from "@/types/api";
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
      planTargets?: string[];
      newFiles?: string[];
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
  planTargets?: string[];
  /** Names in `code` whose body is raw content rather than a diff. */
  newFiles?: string[];
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

/**
 * The round's terraform plan body, or null when it stored none.
 *
 * Position cannot pick it. A round's `plans` interleaves both flavours —
 * the validation loop appends one plan per iteration, the drift pass its
 * diff — and the *newest* entry is routinely a diff: every generate round
 * runs the drift pre-check after validating, and that check stores its
 * diff before it decides there is nothing to remediate
 * (`terraform_drift_service.__store_drift`). Import rounds check drift the
 * same way. So the newest plan-flavoured artifact has to be found, and the
 * flavour is object metadata the read model does not carry.
 *
 * Resolved with ranged probes (`fetchPlanType`, one byte each, all in
 * flight at once) rather than by downloading bodies newest-first: a
 * backward walk would pull a whole drift diff down just to discard it.
 *
 * A round whose plans are all diffs yields null — the Plan tab's empty
 * state, since the diff is already the Report tab's subject. But a round
 * where *no* flavour was readable at all falls back to the newest plan:
 * unreadable metadata (an object stored before the backend wrote it, or a
 * store whose CORS rules hide the header) is not evidence of drift, and
 * blanking the tab across such a deployment would be worse than the
 * pre-existing order guess.
 *
 * `targets` is read off the chosen ref — a sibling of the `url` the body came
 * from — so the addresses always describe the plan actually on screen. That is
 * narrower than "what this round targeted": a remediating drift round writes
 * its targets on the remediation plan, and the validation loop then appends a
 * plan per iteration carrying the validator's usually-empty `terraform_targets`
 * (see `isPartialDrift` in `roundSummary.ts`). When the selected plan is one of
 * those, this yields `[]` rather than the round's addresses, which is the
 * honest answer for a per-artifact label.
 */
async function fetchPlanContent(
  plans: TerraformPlanRef[],
): Promise<{ content: string; targets: string[] } | null> {
  if (plans.length === 0) return null;
  const types = await Promise.all(plans.map((p) => fetchPlanType(p.url)));
  let chosen: TerraformPlanRef | null = null;
  for (let i = plans.length - 1; i >= 0; i--) {
    if (types[i] === "plan") {
      chosen = plans[i];
      break;
    }
  }
  if (!chosen && types.every((t) => t === null)) {
    chosen = plans[plans.length - 1];
  }
  if (!chosen) return null;
  return {
    content: await fetchArtifactContent(chosen.url),
    targets: chosen.targets ?? [],
  };
}

async function fetchRoundArtifacts(
  round: RoundDetail,
  rounds: RoundDetail[],
): Promise<RoundArtifacts> {
  const codeChanges = collectCodeChanges(rounds);
  // Oldest-first, and a round holds exactly one report, so the newest is
  // the round's own — unlike its plans (see `fetchPlanContent`).
  const reportRef: ReportRef | null =
    round.reports[round.reports.length - 1] ?? null;
  const [reportContent, plan, composed] = await Promise.all([
    reportRef ? fetchArtifactContent(reportRef.url) : Promise.resolve(null),
    fetchPlanContent(round.plans),
    // fetchArtifact, not fetchArtifactContent: composing a file's chain
    // needs each artifact's shape, and it rides the same response.
    Promise.all(
      codeChanges.map(async ([fileName, changes]) => {
        const payloads = await Promise.all(
          changes.map((c) => fetchArtifact(c.url)),
        );
        return composeFileArtifacts(
          fileName,
          payloads.map(({ text, isNewFile }) => ({ text, isNewFile })),
        );
      }),
    ),
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
  if (plan) {
    parts.push(`<Terraform_Plan>\n${plan.content}\n</Terraform_Plan>`);
  }
  // The blob flattens each file to text, so the shape has to travel
  // alongside it — `extractCodeFiles` on the other end cannot recover it.
  const newFiles: string[] = [];
  codeChanges.forEach(([fileName], i) => {
    parts.push(`<${fileName}>\n${composed[i].text}\n</${fileName}>`);
    if (composed[i].isNewFile) newFiles.push(fileName);
  });

  // A round with no plan on screen has no addresses to label it with, even
  // when its drift diffs carried some.
  return {
    report,
    code: parts.join("\n"),
    planTargets: plan?.targets ?? [],
    newFiles,
  };
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
      .find(
        (r) =>
          r.reports.length > 0 ||
          r.plans.length > 0 ||
          r.code_changes.length > 0,
      );
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

/** Map an outcome onto the UI Session shape. */
export function buildSessionPatch(outcome: SessionOutcome): Partial<Session> {
  if (outcome.kind === "failed") {
    const patch: Partial<Session> = { current_status: "failed" };
    if (outcome.detail) patch.uuid = outcome.detail.uuid;
    return patch;
  }

  const { detail } = outcome;
  const patch: Partial<Session> = {
    uuid: detail.uuid,
    operation: detail.operation,
    provider: detail.provider,
    scope_id: detail.scope_id,
    first_query: detail.first_query ?? undefined,
    workspace: detail.workspace,
    current_status: detail.current_status,
    is_blocked: detail.is_blocked,
    history: normalizeHistory(detail.history),
  };

  // `planTargets` and `newFiles` are assigned whenever `code` is, never
  // omitted: the patch is merged into the existing session, so leaving a key
  // out would keep the previous round's addresses labelling this round's
  // plan, or tint the wrong file as new.
  if (outcome.kind === "results") {
    patch.terraform_report = outcome.report ?? undefined;
    patch.code = outcome.code;
    patch.planTargets = outcome.planTargets ?? [];
    patch.newFiles = outcome.newFiles ?? [];
  } else if (outcome.kind === "apply-results") {
    patch.terraform_report = outcome.report ?? undefined;
  } else if (outcome.kind === "rejected" && outcome.prior) {
    patch.terraform_report = outcome.prior.report ?? undefined;
    patch.code = outcome.prior.code;
    patch.planTargets = outcome.prior.planTargets ?? [];
    patch.newFiles = outcome.prior.newFiles ?? [];
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
      if (outcome.detail.operation === "import") {
        if (report?.execution_summary) return report.execution_summary;
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
