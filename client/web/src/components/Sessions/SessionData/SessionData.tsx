// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { Fragment, useMemo, useCallback, useState } from "react";
import { useSearchParams } from "react-router-dom";
import Typography from "@mui/material/Typography";
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
import {
  formatDateParts,
  formatDateTime,
  formatDuration,
} from "@/utils/datetime";
import {
  codeChangeLabel,
  isBootstrapRound,
  roundArtifacts,
  roundEvents,
  roundMeta,
  roundTitle,
} from "./roundSummary";
import styles from "./SessionData.module.css";

interface SessionDataProps {
  session: SessionDetail;
  onReload?: () => void;
  onToggleLock?: () => void;
  conversationHistory?: HistoryEntry[];
}

interface SelectedArtifact {
  kind: ArtifactKind;
  artifact: ArtifactRef;
  round: RoundDetail;
}

function capitalize(value: string): string {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

export default function SessionData({
  session,
  onReload,
  onToggleLock,
  conversationHistory,
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
        next.delete("file");
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

  const started = formatDateParts(session.created_at);
  const completed = formatDateParts(session.updated_at);
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
            {formatDuration(session.created_at, session.updated_at)}
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
              {timelineRounds.map((round) => {
                const events = roundEvents(round);
                const meta = roundMeta(round);
                return (
                  <div key={round.id} className={styles.timelineEntry}>
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
                          return (
                            <Fragment key={statusKey}>
                              <div
                                className={`${styles.timelineOpRow}${expandable ? ` ${styles.timelineOpRowClickable}` : ""}`}
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
                                        if (e.key === "Enter")
                                          toggleStatus(statusKey);
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
                                  {capitalize(event.status)}
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
                                {expanded && event.message && (
                                  <div className={styles.timelineOpMessage}>
                                    <MarkdownText content={event.message} />
                                  </div>
                                )}
                              </div>
                              {event.artifacts.map(({ kind, artifact }) => {
                                // `roundArtifacts` widens every row to
                                // `ArtifactRef`, so `kind` is the discriminant
                                // that narrows it back — same as the
                                // `CodeChangeRef` cast below. Only plans carry
                                // targets, and usually only partial-drift ones:
                                // a validation-loop plan's are typically empty.
                                const targets =
                                  kind === "plan"
                                    ? (artifact as TerraformPlanRef).targets
                                    : [];
                                return (
                                  <div
                                    key={`${kind}:${artifact.id}`}
                                    className={`${styles.timelineOpRow} ${styles.timelineOpRowClickable} ${styles.timelineOpRowArtifact}`}
                                    onClick={() =>
                                      setArtifactParam({ kind, artifact })
                                    }
                                    role="button"
                                    tabIndex={0}
                                    onKeyDown={(e) => {
                                      if (e.key === "Enter")
                                        setArtifactParam({ kind, artifact });
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
                                      {kind === "change"
                                        ? codeChangeLabel(
                                            round,
                                            artifact as CodeChangeRef,
                                          )
                                        : artifactLabel(kind, artifact)}
                                      {targets.length > 0 && (
                                        <span
                                          className={styles.timelineOpTargets}
                                          title={targets.join(", ")}
                                        >
                                          {`${STRINGS.sessions.artifactTargets}: ${targets.join(", ")}`}
                                        </span>
                                      )}
                                    </Typography>
                                    <span className={styles.timelineOpDate}>
                                      {formatDateTime(artifact.created_at)}
                                      <VisibilityIcon
                                        className={styles.artifactIcon}
                                      />
                                    </span>
                                  </div>
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

              {/* Terminal state */}
              {isTerminal && (
                <div
                  className={`${styles.timelineEntry} ${styles.timelineEntryLast}${hasFailure ? ` ${styles.timelineEntryFailed}` : ""}`}
                >
                  <div className={styles.timelineDot} />
                  <div className={styles.timelineContent}>
                    <span className={styles.timelinePhase}>
                      {capitalize(session.current_status)}
                    </span>
                    <span className={styles.timelineDate}>
                      {completed.date}
                    </span>
                    <span className={styles.timelineDate}>
                      {completed.time}
                    </span>
                  </div>
                </div>
              )}
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

      {/* ── Conversation History ── */}
      {conversationHistory && conversationHistory.length > 0 && (
        <div className={styles.fieldRow}>
          <Typography
            variant="overline"
            component="span"
            className={styles.fieldLabel}
          >
            History
          </Typography>
          <div className={styles.historyList}>
            {conversationHistory.map((entry, i) => (
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
                {artifactLabel(selected.kind, selected.artifact)}
              </span>
            </span>
          }
        >
          <ArtifactContent
            kind={selected.kind}
            artifact={selected.artifact}
            round={selected.round}
            operation={session.operation}
          />
        </PageOverlay>
      )}
    </div>
  );
}
