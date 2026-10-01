// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { Fragment, useMemo, useCallback, useState } from "react";
import { useSearchParams } from "react-router-dom";
import Typography from "@mui/material/Typography";
import Tooltip from "@mui/material/Tooltip";
import LockOutlinedIcon from "@mui/icons-material/LockOutlined";
import LockOpenOutlinedIcon from "@mui/icons-material/LockOpenOutlined";
import ReplayIcon from "@mui/icons-material/Replay";
import OpenInNewIcon from "@mui/icons-material/OpenInNew";
import VisibilityIcon from "@mui/icons-material/Visibility";
import InsertDriveFileOutlinedIcon from "@mui/icons-material/InsertDriveFileOutlined";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import ExpandLessIcon from "@mui/icons-material/ExpandLess";
import type {
  ArtifactRef,
  CodeChangeRef,
  HistoryEntry,
  RoundDetail,
  SessionDetail,
  TerraformPlanRef,
} from "@/types/api";
import { TERMINAL_STATUSES } from "@/types/api";
import { STRINGS } from "@/constants/strings";
import { providerLabel } from "@/constants/providers";
import { MarkdownText, StatusBadge, PageOverlay } from "@/components/ui";
import ChatMessage from "@/components/Home/ChatHistory/ChatMessage";
import ArtifactContent, { artifactLabel } from "./ArtifactContent";
import type { ArtifactKind } from "./ArtifactContent";
import { usePlanTypes } from "./usePlanTypes";
import {
  formatDateParts,
  formatDateTime,
  formatDuration,
} from "@/utils/datetime";
import {
  codeChangeLabel,
  isBootstrapRound,
  lastStatusAt,
  roundArtifacts,
  roundEvents,
  roundMeta,
  roundTitle,
  statusLabel,
} from "./roundSummary";
import styles from "./SessionData.module.css";

interface SessionDataProps {
  session: SessionDetail;
  onReload?: () => void;
  onToggleLock?: () => void;
  /** The user-facing conversation: one turn per finished round. */
  conversationHistory?: HistoryEntry[];
  /**
   * The internal record the backend feeds to the LLM, shown to admins as
   * debug material. It carries no contract — its shape follows whatever
   * the prompting strategy needs — so it is labelled apart from the
   * conversation rather than merged into it.
   */
  debugHistory?: HistoryEntry[];
}

interface SelectedArtifact {
  kind: ArtifactKind;
  artifact: ArtifactRef;
  round: RoundDetail;
}

function capitalize(value: string): string {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

/**
 * The chip on a plan row. It stands in for the resource list itself, so it
 * names the unit rather than showing a bare number next to a timestamp.
 */
function targetCountLabel(count: number): string {
  const { one, other } = STRINGS.sessions.artifactTargetCount;
  return `${count} ${count === 1 ? one : other}`;
}

export default function SessionData({
  session,
  onReload,
  onToggleLock,
  conversationHistory,
  debugHistory,
}: SessionDataProps) {
  const [searchParams, setSearchParams] = useSearchParams();
  const artifactParam = searchParams.get("artifact");
  const [expandedStatuses, setExpandedStatuses] = useState<Set<string>>(
    () => new Set(),
  );

  const toggleStatus = useCallback((key: string) => {
    setExpandedStatuses((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  }, []);

  // Once for the whole panel, not per row: the timeline and the opened
  // artifact's breadcrumb read the same map.
  const planTypes = usePlanTypes(session.rounds);

  const selected: SelectedArtifact | null = useMemo(() => {
    if (!artifactParam) return null;
    const [kind, idStr] = artifactParam.split(":");
    const id = Number(idStr);
    for (const round of session.rounds) {
      for (const row of roundArtifacts(round)) {
        if (row.kind === kind && row.artifact.id === id) {
          return { kind: row.kind, artifact: row.artifact, round };
        }
      }
    }
    return null;
  }, [artifactParam, session.rounds]);

  const setArtifactParam = useCallback(
    (value: { kind: ArtifactKind; artifact: ArtifactRef } | null) => {
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev);
        if (value) {
          next.set("artifact", `${value.kind}:${value.artifact.id}`);
        } else {
          next.delete("artifact");
        }
        next.delete("detail");
        next.delete("resource");
        next.delete("filter");
        return next;
      });
    },
    [setSearchParams],
  );

  const isTerminal = TERMINAL_STATUSES.includes(session.current_status);
  const hasFailure =
    session.current_status === "failed" ||
    session.current_status === "uncompleted";
  const failureMessage = useMemo(() => {
    if (!hasFailure) return null;
    const failed = session.rounds
      .flatMap((r) => r.statuses)
      .reverse()
      .find((s) => s.status === "failed" || s.status === "uncompleted");
    return failed?.message || null;
  }, [hasFailure, session.rounds]);

  // `create_session` opens an empty shell round with the same query the
  // working round gets, so rendering it would duplicate the user's action.
  // Its message is the only thing worth keeping, and it belongs on Started.
  const timelineRounds = useMemo(
    () => session.rounds.filter((r) => !isBootstrapRound(r)),
    [session.rounds],
  );
  const bootstrapMessage = useMemo(
    () => session.rounds.find(isBootstrapRound)?.statuses[0]?.message || null,
    [session.rounds],
  );

  // `roundEvents` parses and sorts every status and artifact of a round,
  // and both the heading's count and the rows below it need the result.
  // Derived here rather than in the render body because `expandedStatuses`
  // is component state: every expand/collapse re-runs that body.
  const roundViews = useMemo(
    () =>
      timelineRounds.map((round) => {
        const events = roundEvents(round);
        return { round, events, meta: roundMeta(events) };
      }),
    [timelineRounds],
  );

  // The last round *with events*, not simply the last one: `create_round`
  // opens the next round before its first status lands, and that round stays
  // visible on purpose (see `isBootstrapRound`) while `current_status` still
  // reports the previous round's terminal value. Indexing alone would put
  // the marker on a round with no row to carry it.
  const closingIndex = useMemo(() => {
    if (!isTerminal) return -1;
    for (let i = roundViews.length - 1; i >= 0; i--) {
      if (roundViews[i].events.length > 0) return i;
    }
    return -1;
  }, [isTerminal, roundViews]);

  const started = formatDateParts(session.created_at);
  // `updated_at` is the fallback only for a session with no status at all,
  // which the duration row's `isTerminal` guard already rules out. See
  // `lastStatusAt` for why it is not the primary source.
  const finishedAt = lastStatusAt(session) ?? session.updated_at;
  const hasTimeline = session.rounds.length > 0;
  const lockIcon = session.is_blocked ? (
    <LockOutlinedIcon className={styles.btnIcon} />
  ) : (
    <LockOpenOutlinedIcon className={styles.btnIcon} />
  );
  const lockLabel = session.is_blocked ? "Apply Locked" : "Apply Open";

  return (
    <div className={styles.container}>
      {/* ── Metadata Fields ── */}
      <div className={styles.fieldRow}>
        <Typography
          variant="overline"
          component="span"
          className={styles.fieldLabel}
        >
          Type
        </Typography>
        <Typography
          variant="body1"
          component="span"
          className={styles.fieldValue}
        >
          {capitalize(session.operation)}
        </Typography>
      </div>
      <div className={styles.fieldRow}>
        <Typography
          variant="overline"
          component="span"
          className={styles.fieldLabel}
        >
          Cloud
        </Typography>
        <Typography
          variant="body1"
          component="span"
          className={styles.fieldValue}
        >
          {providerLabel(session.provider)}
        </Typography>
      </div>
      <div className={styles.fieldRow}>
        <Typography
          variant="overline"
          component="span"
          className={styles.fieldLabel}
        >
          Status
        </Typography>
        <div className={styles.fieldValue}>
          <StatusBadge variant={session.current_status} />
        </div>
      </div>
      {failureMessage && (
        <div className={styles.fieldRow}>
          <Typography
            variant="overline"
            component="span"
            className={styles.fieldLabel}
          >
            Failure
          </Typography>
          <Typography
            variant="body1"
            component="div"
            className={`${styles.fieldValue} ${styles.failureValue}`}
          >
            <MarkdownText content={failureMessage} />
          </Typography>
        </div>
      )}
      {isTerminal && (
        <div className={styles.fieldRow}>
          <Typography
            variant="overline"
            component="span"
            className={styles.fieldLabel}
          >
            Duration
          </Typography>
          <Typography
            variant="body1"
            component="span"
            className={styles.fieldValue}
          >
            {formatDuration(session.created_at, finishedAt)}
          </Typography>
        </div>
      )}

      {/* ── Timeline ── */}
      <div className={styles.fieldRow}>
        <Typography
          variant="overline"
          component="span"
          className={styles.fieldLabel}
        >
          Timeline
        </Typography>
        <div className={styles.timeline}>
          {!hasTimeline ? (
            <p className={styles.timelineEmpty}>No activity recorded</p>
          ) : (
            <>
              {/* STARTED */}
              <div className={styles.timelineEntry}>
                <div className={styles.timelineDot} />
                <div className={styles.timelineContent}>
                  <span className={styles.timelinePhase}>Started</span>
                  <span className={styles.timelineDate}>{started.date}</span>
                  <span className={styles.timelineDate}>{started.time}</span>
                  {bootstrapMessage && (
                    <span className={styles.timelineMessage}>
                      {bootstrapMessage}
                    </span>
                  )}
                </div>
              </div>

              {/* Rounds */}
              {roundViews.map(({ round, events, meta }, roundIndex) => {
                const closing = roundIndex === closingIndex;
                // The connector line stops only when the closing round is
                // also the last thing rendered: a round opened after it
                // means work resumed, and the trailing line says so.
                const endsTimeline =
                  closing && roundIndex === roundViews.length - 1;
                return (
                  <div
                    key={round.id}
                    className={`${styles.timelineEntry}${endsTimeline ? ` ${styles.timelineEntryLast}` : ""}${closing && hasFailure ? ` ${styles.timelineEntryFailed}` : ""}`}
                  >
                    <div className={styles.timelineDot} />
                    <div className={styles.timelineContent}>
                      <span className={styles.timelinePhase}>
                        {roundTitle(round, session)}
                      </span>
                      <span className={styles.timelineQuery}>
                        {round.query}
                      </span>
                      {meta.length > 0 && (
                        <Typography
                          variant="overline"
                          component="span"
                          className={styles.timelineCount}
                        >
                          {meta.join(" · ")}
                        </Typography>
                      )}
                      {/* One row per event, with the artifacts that event
                          produced nested directly beneath it. */}
                      <div className={styles.timelineOps}>
                        {events.map((event, i) => {
                          const statusKey = `${round.id}:${i}`;
                          const expandable = !!event.message;
                          const expanded = expandedStatuses.has(statusKey);
                          // Only the final event of the closing round can
                          // hold the session's resting state.
                          const isClosing =
                            closing &&
                            i === events.length - 1 &&
                            TERMINAL_STATUSES.includes(event.status);
                          const rowClass = [
                            styles.timelineOpRow,
                            expandable && styles.timelineOpRowClickable,
                            isClosing && styles.timelineOpRowTerminal,
                            isClosing &&
                              hasFailure &&
                              styles.timelineOpRowFailed,
                          ]
                            .filter(Boolean)
                            .join(" ");
                          return (
                            <Fragment key={statusKey}>
                              <div
                                className={rowClass}
                                onClick={
                                  expandable
                                    ? () => toggleStatus(statusKey)
                                    : undefined
                                }
                                role={expandable ? "button" : undefined}
                                tabIndex={expandable ? 0 : undefined}
                                onKeyDown={
                                  expandable
                                    ? (e) => {
                                        // `role="button"` promises both keys;
                                        // Space scrolls unless claimed here.
                                        if (
                                          e.key === "Enter" ||
                                          e.key === " "
                                        ) {
                                          e.preventDefault();
                                          toggleStatus(statusKey);
                                        }
                                      }
                                    : undefined
                                }
                                aria-expanded={
                                  expandable ? expanded : undefined
                                }
                              >
                                <Typography
                                  variant="subtitle2"
                                  component="div"
                                  className={styles.timelineOpName}
                                >
                                  {statusLabel(event.status)}
                                </Typography>
                                <span className={styles.timelineOpDate}>
                                  {formatDateTime(event.created_at)}
                                  {expandable &&
                                    (expanded ? (
                                      <ExpandLessIcon
                                        className={styles.artifactIcon}
                                      />
                                    ) : (
                                      <ExpandMoreIcon
                                        className={styles.artifactIcon}
                                      />
                                    ))}
                                </span>
                              </div>
                              {/* Outside the row: a status message can
                                  contain links, and interactive content
                                  nested in `role="button"` is invalid. */}
                              {expanded && event.message && (
                                <div className={styles.timelineOpMessage}>
                                  <MarkdownText content={event.message} />
                                </div>
                              )}
                              {event.artifacts.map(({ kind, artifact }) => {
                                // `roundArtifacts` widens every row to
                                // `ArtifactRef`, so `kind` narrows it back —
                                // same as the `CodeChangeRef` cast below.
                                const targets =
                                  kind === "plan"
                                    ? (artifact as TerraformPlanRef).targets
                                    : [];
                                const label =
                                  kind === "change"
                                    ? codeChangeLabel(
                                        round,
                                        artifact as CodeChangeRef,
                                      )
                                    : artifactLabel(
                                        kind,
                                        artifact,
                                        planTypes.get(artifact.id),
                                      );
                                return (
                                  <Tooltip
                                    key={`${kind}:${artifact.id}`}
                                    title={
                                      targets.length > 0
                                        ? targets.map((target) => (
                                            <div key={target}>{target}</div>
                                          ))
                                        : ""
                                    }
                                    describeChild
                                  >
                                    <div
                                      className={`${styles.timelineOpRow} ${styles.timelineOpRowClickable} ${styles.timelineOpRowArtifact}`}
                                      onClick={() =>
                                        setArtifactParam({ kind, artifact })
                                      }
                                      role="button"
                                      tabIndex={0}
                                      aria-label={`${STRINGS.sessions.artifactOpen} ${label}`}
                                      onKeyDown={(e) => {
                                        if (e.key === "Enter" || e.key === " ") {
                                          e.preventDefault();
                                          setArtifactParam({ kind, artifact });
                                        }
                                      }}
                                    >
                                      <Typography
                                        variant="subtitle2"
                                        component="div"
                                        className={styles.timelineOpName}
                                      >
                                        <InsertDriveFileOutlinedIcon
                                          className={styles.artifactFileIcon}
                                        />
                                        {label}
                                      </Typography>
                                      {targets.length > 0 && (
                                        <span
                                          className={styles.timelineOpTargetChip}
                                        >
                                          {targetCountLabel(targets.length)}
                                        </span>
                                      )}
                                      <span className={styles.timelineOpDate}>
                                        {formatDateTime(artifact.created_at)}
                                        <VisibilityIcon
                                          className={styles.artifactIcon}
                                        />
                                      </span>
                                    </div>
                                  </Tooltip>
                                );
                              })}
                            </Fragment>
                          );
                        })}
                      </div>
                    </div>
                  </div>
                );
              })}
            </>
          )}
        </div>
      </div>

      {/* ── Additional Information ── */}
      <div className={styles.fieldRow}>
        <Typography
          variant="overline"
          component="span"
          className={styles.fieldLabel}
        >
          Additional Info
        </Typography>
        <div className={styles.infoContent}>
          <div className={styles.infoRow}>
            <Typography
              variant="subtitleSemiBold"
              component="span"
              className={styles.infoLabel}
            >
              Session ID
            </Typography>
            <Typography
              variant="subtitle2"
              component="span"
              className={styles.uuidValue}
            >
              {session.uuid}
            </Typography>
          </div>
          {session.workspace.root_path && (
            <div className={styles.infoRow}>
              <Typography
                variant="subtitleSemiBold"
                component="span"
                className={styles.infoLabel}
              >
                Path
              </Typography>
              <Typography
                variant="subtitle2"
                component="span"
                className={styles.infoValue}
              >
                {session.workspace.root_path}
              </Typography>
            </div>
          )}
          <div className={styles.infoRow}>
            <Typography
              variant="subtitleSemiBold"
              component="span"
              className={styles.infoLabel}
            >
              {STRINGS.wizard.scopeByProvider[session.provider]?.label ??
                "Scope"}
            </Typography>
            <Typography
              variant="subtitle2"
              component="span"
              className={styles.infoValue}
            >
              {session.scope_id}
            </Typography>
          </div>
          <div className={styles.infoRow}>
            <Typography
              variant="subtitleSemiBold"
              component="span"
              className={styles.infoLabel}
            >
              Links
            </Typography>
            <div className={styles.linksCol}>
              <a
                href={session.workspace.uri}
                target="_blank"
                rel="noopener noreferrer"
                className={styles.link}
              >
                Repository
                <OpenInNewIcon className={styles.linkIcon} />
              </a>
              {(
                session.rounds[session.rounds.length - 1]?.pull_requests ?? []
              ).map((pr) => (
                <a
                  key={pr.url}
                  href={pr.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className={styles.link}
                >
                  Pull Request #{pr.number}
                  <OpenInNewIcon className={styles.linkIcon} />
                </a>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* ── Conversation ── */}
      {conversationHistory && conversationHistory.length > 0 && (
        <div className={styles.fieldRow}>
          <Typography
            variant="overline"
            component="span"
            className={styles.fieldLabel}
          >
            Conversation
          </Typography>
          <div className={styles.historyList}>
            {conversationHistory.map((entry, i) => (
              <ChatMessage key={i} role={entry.role} content={entry.content} />
            ))}
          </div>
        </div>
      )}

      {/* ── Internal history (admin debug) ── */}
      {debugHistory && debugHistory.length > 0 && (
        <div className={styles.fieldRow}>
          <Typography
            variant="overline"
            component="span"
            className={styles.fieldLabel}
          >
            Internal history
          </Typography>
          <div className={styles.historyList}>
            {debugHistory.map((entry, i) => (
              <ChatMessage key={i} role={entry.role} content={entry.content} />
            ))}
          </div>
        </div>
      )}

      {/* ── Action Buttons ── */}
      <div className={styles.actions}>
        {onToggleLock ? (
          <button
            type="button"
            className={
              session.is_blocked
                ? styles.btnApplyInteractive
                : styles.btnApplyOpenInteractive
            }
            title={session.is_blocked ? "Unlock apply" : "Lock apply"}
            onClick={onToggleLock}
          >
            {lockIcon}
            {lockLabel}
          </button>
        ) : (
          <span
            className={
              session.is_blocked ? styles.btnApply : styles.btnApplyOpen
            }
          >
            {lockIcon}
            {lockLabel}
          </span>
        )}
        {onReload && (
          <button type="button" className={styles.btnReload} onClick={onReload}>
            <ReplayIcon className={styles.btnIcon} />
            Reload Session
          </button>
        )}
      </div>

      {selected && (
        <PageOverlay
          onClose={() => setArtifactParam(null)}
          title={
            <span className={styles.breadcrumb}>
              <span className={styles.breadcrumbPath}>
                <span>{session.first_query || "Session"}</span>
                <Typography
                  variant="micro"
                  component="span"
                  className={styles.breadcrumbSeparator}
                >
                  /
                </Typography>
                <span>{roundTitle(selected.round, session)}</span>
              </span>
              <span className={styles.breadcrumbCurrent}>
                {artifactLabel(
                  selected.kind,
                  selected.artifact,
                  planTypes.get(selected.artifact.id),
                )}
              </span>
            </span>
          }
        >
          <ArtifactContent
            kind={selected.kind}
            artifact={selected.artifact}
            operation={session.operation}
            onPlanType={planTypes.record}
          />
        </PageOverlay>
      )}
    </div>
  );
}
