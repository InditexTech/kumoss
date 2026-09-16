// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import type {
  ArtifactRef,
  CodeChangeRef,
  RoundDetail,
  SessionDetail,
  SessionStatus,
} from "@/types/api";
import { isApplyRound } from "@/services/workflows/session_outcome";
import type { ArtifactKind } from "./ArtifactContent";

/**
 * What a round did. A round is one *operation invocation* — `next_round()`
 * is called once at the top of each background task — not one iteration of
 * the generate/validate loop, which runs *inside* a round. So the ordinal
 * the timeline used to show conveyed nothing the user thinks in.
 */
export type RoundKind = "generate" | "drift" | "import" | "apply";

export type ArtifactRow = { kind: ArtifactKind; artifact: ArtifactRef };

const KIND_LABELS: Record<RoundKind, string> = {
  generate: "Code Generation",
  drift: "Drift Analysis",
  import: "Import",
  apply: "Terraform Apply",
};

/** Only non-success resting states earn a suffix; success needs no words. */
const OUTCOME_SUFFIXES: Partial<Record<SessionStatus, string>> = {
  failed: " — Failed",
  uncompleted: " — Incomplete",
};

/**
 * The report type is the most authoritative signal, but a failed round never
 * produces one — hence the two fallbacks. `session.operation` cannot be
 * "apply" (apply reuses the session's stored plan and keeps the original
 * operation), which is why the apply-status probe has to come first.
 */
export function roundKind(
  round: RoundDetail,
  session: SessionDetail,
): RoundKind {
  if (round.report) return round.report.type;
  if (isApplyRound(round)) return "apply";
  return session.operation;
}

/**
 * Partial drift is the only flow that populates `targets`: the drift handler
 * sets `targets = []` and fills it only under `if is_partial`. Generation
 * plans carry targets too, so this is meaningful only once the kind is known
 * to be drift.
 */
function isPartialDrift(round: RoundDetail, kind: RoundKind): boolean {
  return kind === "drift" && (round.plan?.targets.length ?? 0) > 0;
}

/** Statuses arrive sorted by (created_at, id), so the last one is current. */
function lastStatus(round: RoundDetail): SessionStatus | undefined {
  return round.statuses[round.statuses.length - 1]?.status;
}

export function roundTitle(round: RoundDetail, session: SessionDetail): string {
  const kind = roundKind(round, session);
  const partial = isPartialDrift(round, kind) ? " (partial)" : "";
  const last = lastStatus(round);
  const suffix = last ? (OUTCOME_SUFFIXES[last] ?? "") : "";
  return `${KIND_LABELS[kind]}${partial}${suffix}`;
}

/** Every artifact of a round, flattened into openable rows. */
export function roundArtifacts(round: RoundDetail): ArtifactRow[] {
  const rows: ArtifactRow[] = [];
  if (round.report) rows.push({ kind: "report", artifact: round.report });
  if (round.plan) rows.push({ kind: "plan", artifact: round.plan });
  for (const change of round.code_changes) {
    rows.push({ kind: "change", artifact: change });
  }
  return rows;
}

/**
 * Dot-separated meta parts, zero-valued ones omitted.
 *
 * Files are counted **distinct**: `code_changes` holds one row per write, so
 * a file rewritten on a later validation pass appears twice and a naive row
 * count inflates with every retry. No pass count — counting `generating`
 * statuses would conflate generation passes with the automatic drift
 * reconciliation passes that land in the same round, and the read model
 * cannot currently tell them apart.
 */
export function roundMeta(round: RoundDetail): string[] {
  const parts: string[] = [];
  const files = new Set(round.code_changes.map((c) => c.file_name)).size;
  if (files > 0) parts.push(`${files} FILE${files !== 1 ? "S" : ""}`);
  const artifacts = roundArtifacts(round).length;
  if (artifacts > 0) {
    parts.push(`${artifacts} ARTIFACT${artifacts !== 1 ? "S" : ""}`);
  }
  return parts;
}

/**
 * `create_session` opens a round carrying only the user's query and a
 * `started` status, then the handler immediately opens a second round with
 * the *same* query where all work happens. So one user action renders as two
 * timeline entries with identical text unless the shell is collapsed.
 *
 * `statuses.length > 0` is load-bearing: `[].every()` is `true`, and a round
 * that has been INSERTed but not yet had its first status written is a real
 * state. Such a round must stay visible, not be mistaken for the shell.
 * Working rounds never write `started` — they open at `filtering` or
 * `apply` — so this cannot swallow one.
 */
export function isBootstrapRound(round: RoundDetail): boolean {
  return (
    !round.report &&
    !round.plan &&
    round.code_changes.length === 0 &&
    round.pull_requests.length === 0 &&
    round.statuses.length > 0 &&
    round.statuses.every((s) => s.status === "started")
  );
}

/**
 * Two `code_changes` with the same `file_name` render as two identical rows,
 * and clicking either is a coin flip. Append a revision index only when a
 * name actually repeats within the round. The index is round-scoped, which
 * is why this cannot live in `artifactLabel`.
 *
 * `code_changes` arrives oldest-first (the backend sorts by created_at, id),
 * so array order is revision order.
 */
export function codeChangeLabel(
  round: RoundDetail,
  change: CodeChangeRef,
): string {
  const sameName = round.code_changes.filter(
    (c) => c.file_name === change.file_name,
  );
  if (sameName.length < 2) return change.file_name;
  const rev = sameName.findIndex((c) => c.id === change.id) + 1;
  return `${change.file_name} (rev ${rev})`;
}
