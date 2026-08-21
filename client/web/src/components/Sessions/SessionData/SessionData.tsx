// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { useMemo, useCallback } from "react";
import { useSearchParams } from "react-router-dom";
import Typography from "@mui/material/Typography";
import LockOutlinedIcon from "@mui/icons-material/LockOutlined";
import LockOpenOutlinedIcon from "@mui/icons-material/LockOpenOutlined";
import ReplayIcon from "@mui/icons-material/Replay";
import OpenInNewIcon from "@mui/icons-material/OpenInNew";
import VisibilityIcon from "@mui/icons-material/Visibility";
import InsertDriveFileOutlinedIcon from "@mui/icons-material/InsertDriveFileOutlined";
import type {
  ArtifactRef,
  HistoryEntry,
  RoundDetail,
  SessionDetail,
} from "@/types/api";
import { TERMINAL_STATUSES } from "@/types/api";
import { STRINGS } from "@/constants/strings";
import { providerLabel } from "@/constants/providers";
import { MarkdownText, StatusBadge, PageOverlay } from "@/components/ui";
import ChatMessage from "@/components/Home/ChatHistory/ChatMessage";
import ArtifactContent, { artifactLabel } from "./ArtifactContent";
import type { ArtifactKind } from "./ArtifactContent";
import styles from "./SessionData.module.css";

interface SessionDataProps {
  session: SessionDetail;
  onReload?: () => void;
  conversationHistory?: HistoryEntry[];
}

interface SelectedArtifact {
  kind: ArtifactKind;
  artifact: ArtifactRef;
  round: RoundDetail;
}

function formatShortDate(iso: string | undefined | null): {
  date: string;
  time: string;
} {
  if (!iso) return { date: "-", time: "" };
  const d = new Date(iso);
  const dd = String(d.getDate()).padStart(2, "0");
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const yy = String(d.getFullYear()).slice(-2);
  const hh = String(d.getHours()).padStart(2, "0");
  const min = String(d.getMinutes()).padStart(2, "0");
  return { date: `${dd}.${mm}.${yy}`, time: `${hh}:${min}` };
}

function formatOpDate(iso: string | undefined | null): string {
  if (!iso) return "-";
  const d = new Date(iso);
  const dd = String(d.getDate()).padStart(2, "0");
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const yyyy = d.getFullYear();
  const hh = String(d.getHours()).padStart(2, "0");
  const min = String(d.getMinutes()).padStart(2, "0");
  return `${dd}.${mm}.${yyyy}, ${hh}:${min}`;
}

function formatDuration(startIso: string, endIso: string): string {
  const seconds = (new Date(endIso).getTime() - new Date(startIso).getTime()) / 1000;
  if (seconds < 0) return "-";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
}

function capitalize(value: string): string {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

/** Every artifact of a round, flattened into openable rows. */
function roundArtifacts(
  round: RoundDetail,
): { kind: ArtifactKind; artifact: ArtifactRef }[] {
  const rows: { kind: ArtifactKind; artifact: ArtifactRef }[] = [];
  if (round.report) rows.push({ kind: "report", artifact: round.report });
  if (round.plan) rows.push({ kind: "plan", artifact: round.plan });
  for (const change of round.code_changes) {
    rows.push({ kind: "change", artifact: change });
  }
  return rows;
}

export default function SessionData({
  session,
  onReload,
  conversationHistory,
}: SessionDataProps) {
  const [searchParams, setSearchParams] = useSearchParams();
  const artifactParam = searchParams.get("artifact");

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
    const failed = [...session.statuses]
      .reverse()
      .find((s) => s.status === "failed" || s.status === "uncompleted");
    return failed?.message || null;
  }, [hasFailure, session.statuses]);

  const started = formatShortDate(session.created_at);
  const completed = formatShortDate(session.updated_at);
  const hasTimeline = session.rounds.length > 0 || session.statuses.length > 0;

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
                </div>
              </div>

              {/* Rounds */}
              {session.rounds.map((round) => {
                const artifacts = roundArtifacts(round);
                return (
                  <div key={round.id} className={styles.timelineEntry}>
                    <div className={styles.timelineDot} />
                    <div className={styles.timelineContent}>
                      <span className={styles.timelinePhase}>
                        Round {round.number}
                      </span>
                      <Typography
                        variant="overline"
                        component="span"
                        className={styles.timelineCount}
                      >
                        {artifacts.length} ARTIFACT
                        {artifacts.length !== 1 ? "S" : ""}
                      </Typography>
                      <div className={styles.timelineOps}>
                        {round.statuses.length > 0 && (
                          <div className={styles.timelineOpGroup}>
                            <Typography
                              variant="overline"
                              component="span"
                              className={styles.timelineOpGroupLabel}
                            >
                              Statuses
                            </Typography>
                            <span className={styles.timelineOpGroupFill} />
                          </div>
                        )}
                        {round.statuses.map((st, i) => (
                          <div
                            key={`st-${i}`}
                            className={styles.timelineOpRow}
                            title={st.message || undefined}
                          >
                            <Typography
                              variant="subtitle2"
                              component="span"
                              className={styles.timelineOpName}
                            >
                              {capitalize(st.status)}
                            </Typography>
                            <span className={styles.timelineOpDate}>
                              {formatOpDate(st.created_at)}
                            </span>
                          </div>
                        ))}
                        {artifacts.length > 0 && (
                          <div className={styles.timelineOpGroup}>
                            <Typography
                              variant="overline"
                              component="span"
                              className={styles.timelineOpGroupLabel}
                            >
                              Artifacts
                            </Typography>
                            <span className={styles.timelineOpGroupFill} />
                          </div>
                        )}
                        {artifacts.map(({ kind, artifact }) => (
                          <div
                            key={`${kind}:${artifact.id}`}
                            className={`${styles.timelineOpRow} ${styles.timelineOpRowClickable} ${styles.timelineOpRowArtifact}`}
                            onClick={() => setArtifactParam({ kind, artifact })}
                            role="button"
                            tabIndex={0}
                            onKeyDown={(e) => {
                              if (e.key === "Enter")
                                setArtifactParam({ kind, artifact });
                            }}
                          >
                            <Typography
                              variant="subtitle2"
                              component="span"
                              className={styles.timelineOpName}
                            >
                              <InsertDriveFileOutlinedIcon
                                className={styles.artifactFileIcon}
                              />
                              {artifactLabel(kind, artifact)}
                            </Typography>
                            <span className={styles.timelineOpDate}>
                              {formatOpDate(artifact.created_at)}
                              <VisibilityIcon className={styles.artifactIcon} />
                            </span>
                          </div>
                        ))}
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
        <span
          className={
            session.is_blocked ? styles.btnApply : styles.btnApplyOpen
          }
        >
          {session.is_blocked ? (
            <LockOutlinedIcon className={styles.btnIcon} />
          ) : (
            <LockOpenOutlinedIcon className={styles.btnIcon} />
          )}
          {session.is_blocked ? "Apply Locked" : "Apply Open"}
        </span>
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
                <span>Round {selected.round.number}</span>
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
