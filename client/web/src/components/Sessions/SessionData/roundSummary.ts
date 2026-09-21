// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import type {
  ArtifactRef,
  CodeChangeRef,
  ReportRef,
  RoundDetail,
  SessionDetail,
  SessionStatus,
} from "@/types/api";
import { isApplyRound } from "@/services/workflows/session_outcome";
import { STRINGS } from "@/constants/strings";
import type { ArtifactKind } from "./ArtifactContent";

/**
 * What a round did. A round is one *operation invocation* — `next_round()`
 * is called once at the top of each background task — not one iteration of
 * the generate/validate loop, which runs *inside* a round. So the ordinal
 * the timeline used to show conveyed nothing the user thinks in.
 */
export type RoundKind = "generate" | "drift" | "import" | "apply";

export type ArtifactRow = { kind: ArtifactKind; artifact: ArtifactRef };

/**
 * Copy lives in `STRINGS`; the annotations stay here. `Record<RoundKind, _>`
 * is total, so adding a member to `RoundKind` fails this assignment until
 * the label exists.
 */
const KIND_LABELS: Record<RoundKind, string> = STRINGS.sessions.roundKinds;

/** Only non-success resting states earn a suffix; success needs no words. */
const OUTCOME_SUFFIXES: Partial<Record<SessionStatus, string>> =
  STRINGS.sessions.roundOutcomeSuffixes;

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
  // Oldest-first, so the round's own kind is the newest report's.
  const report: ReportRef | undefined = round.reports[round.reports.length - 1];
  if (report) return report.type;
  if (isApplyRound(round)) return "apply";
  return session.operation;
}

/**
 * Partial drift is the only flow that populates `targets`: the drift handler
 * sets `targets = []` and fills it only under `if is_partial`. Generation
 * plans carry targets too, so this is meaningful only once the kind is known
 * to be drift.
 *
 * Checked across every plan, not just the newest. A remediating drift round
 * writes the drift diff and its plan with the handler's targets
 * (`terraform_drift_service.__upload_artifacts`), then the nested validation
 * service appends one plan per iteration carrying the validator's
 * `terraform_targets`, which are usually empty. The newest plan is therefore
 * the wrong one to ask.
 */
function isPartialDrift(round: RoundDetail, kind: RoundKind): boolean {
  return kind === "drift" && round.plans.some((p) => p.targets.length > 0);
}

/** Statuses arrive sorted by (created_at, id), so the last one is current. */
function lastStatus(round: RoundDetail): SessionStatus | undefined {
  return round.statuses[round.statuses.length - 1]?.status;
}

export function roundTitle(round: RoundDetail, session: SessionDetail): string {
  const kind = roundKind(round, session);
  const partial = isPartialDrift(round, kind)
    ? STRINGS.sessions.roundPartialSuffix
    : "";
  const last = lastStatus(round);
  const suffix = last ? (OUTCOME_SUFFIXES[last] ?? "") : "";
  return `${KIND_LABELS[kind]}${partial}${suffix}`;
}

/** Every artifact of a round, flattened into openable rows. */
export function roundArtifacts(round: RoundDetail): ArtifactRow[] {
  const rows: ArtifactRow[] = [];
  for (const report of round.reports) {
    rows.push({ kind: "report", artifact: report });
  }
  for (const plan of round.plans) rows.push({ kind: "plan", artifact: plan });
  for (const change of round.code_changes) {
    rows.push({ kind: "change", artifact: change });
  }
  return rows;
}

/**
 * One entry of a round's timeline: a status update, plus whatever artifacts
 * that status produced. Most statuses produce none.
 */
export type TimelineEvent = {
  status: SessionStatus;
  message: string | null;
  created_at: string;
  artifacts: ArtifactRow[];
};

/**
 * A round's statuses and artifacts merged into one chronological sequence.
 *
 * Nothing in the payload links an artifact to a status — `code_changes`,
 * `reports` and `terraform_plans` carry only `round_id` — so the link is
 * derived from time. That derivation is exact rather than heuristic because
 * every writer persists the status *before* the artifact and never
 * interleaves two stages: `generating` is followed by one `store_code_change`
 * per changed file, `validating` by at most one plan, `report` by one report.
 * So an artifact belongs to the last status at or before its own instant.
 *
 * Two consequences worth knowing:
 *  - `started`, `filtering`, `apply`, `completed`, `uncompleted` and `failed`
 *    never carry artifacts. That falls out of the rule; it is not hardcoded.
 *  - The read model returns *every* plan and report of a round, oldest
 *    first, so each `validating` / `reconciling` pass carries the plan it
 *    actually produced. Under the old latest-wins read model the earlier
 *    passes were bare, and a drift diff could never be shown next to the
 *    plan it produced.
 *
 * A round with no statuses yet (INSERTed, first status still unwritten) has
 * no events. It cannot own artifacts either, since every writer statuses
 * first.
 */
export function roundEvents(round: RoundDetail): TimelineEvent[] {
  // Statuses arrive sorted by (created_at, id), so this is already ordered.
  const events: TimelineEvent[] = round.statuses.map((st) => ({
    status: st.status,
    message: st.message,
    created_at: st.created_at,
    artifacts: [],
  }));
  if (events.length === 0) return events;

  const eventAt = events.map((e) => Date.parse(e.created_at));
  const ordered = [...roundArtifacts(round)].sort(
    (a, b) =>
      Date.parse(a.artifact.created_at) - Date.parse(b.artifact.created_at),
  );

  for (const row of ordered) {
    const stamp = Date.parse(row.artifact.created_at);
    // Scanning backwards takes the *last* status at or before the artifact;
    // `<=` puts an artifact sharing its status's instant on that status.
    // Falling through to 0 clamps an artifact older than every status onto
    // the first event rather than dropping it.
    let index = 0;
    for (let i = events.length - 1; i >= 0; i--) {
      if (eventAt[i] <= stamp) {
        index = i;
        break;
      }
    }
    events[index].artifacts.push(row);
  }

  return events;
}

/**
 * Dot-separated meta parts, zero-valued ones omitted.
 *
 * The count is of *events* — what the section below it actually lists. File
 * and artifact counts used to live here, but they double-counted what the
 * rows already show: artifacts are now nested under the event that produced
 * them, and `code_changes` holds one row per write, so a file rewritten on a
 * later validation pass was inflating the total either way.
 *
 * Takes the events rather than the round so the caller derives them once:
 * `roundEvents` parses and sorts every status and artifact, and the render
 * path needs that same list to draw the rows.
 */
export function roundMeta(events: TimelineEvent[]): string[] {
  if (events.length === 0) return [];
  return [`${events.length} EVENT${events.length !== 1 ? "S" : ""}`];
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
    round.reports.length === 0 &&
    round.plans.length === 0 &&
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

/**
 * When the session actually last did something, or `null` if nothing has
 * been recorded yet.
 *
 * `updated_at` is a last-modified column carrying `onupdate` (see
 * `core/src/infrastructure/database/models.py`), so *any* write to the row
 * moves it — `set_lock`, the `in_flight` release. Toggling the apply lock on
 * a session that finished hours earlier would inflate its duration and drag
 * its "Completed" timestamp forward. The newest status is the real one.
 *
 * Takes the last status of each round rather than flattening every status:
 * a round's statuses are already chronological. The comparison is a plain
 * string compare because these are ISO-8601 UTC instants, which sort
 * lexicographically — the timeline's own ordering relies on the same thing.
 */
export function lastStatusAt(session: SessionDetail): string | null {
  let newest: string | null = null;
  for (const round of session.rounds) {
    const last = round.statuses[round.statuses.length - 1];
    if (last && (!newest || last.created_at > newest)) {
      newest = last.created_at;
    }
  }
  return newest;
}
