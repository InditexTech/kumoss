import { useMemo, useCallback } from "react";
import { useSearchParams } from "react-router-dom";
import Typography from "@mui/material/Typography";
import LockOutlinedIcon from "@mui/icons-material/LockOutlined";
import LockOpenOutlinedIcon from "@mui/icons-material/LockOpenOutlined";
import ReplayIcon from "@mui/icons-material/Replay";
import OpenInNewIcon from "@mui/icons-material/OpenInNew";
import VisibilityIcon from "@mui/icons-material/Visibility";
import type { AdminOperationItem, HistoryEntry } from "@/types/api";
import { StatusBadge, PageOverlay } from "@/components/ui";
import ChatMessage from "@/components/Home/ChatHistory/ChatMessage";
import type { SessionItem } from "../types";
import { isAdminSession } from "../types";
import ArtifactContent, { formatArtifactLabel } from "./ArtifactContent";
import styles from "./SessionData.module.css";

interface SessionDataProps {
  session: SessionItem;
  operations: AdminOperationItem[];
  onReload?: () => void;
  onToggleApply?: () => void;
  conversationHistory?: HistoryEntry[];
}

interface PhaseGroup {
  phase: string;
  operations: AdminOperationItem[];
}

function groupByPhase(operations: AdminOperationItem[]): PhaseGroup[] {
  const groups: PhaseGroup[] = [];
  let current: PhaseGroup | null = null;

  for (const op of operations) {
    const phase = op.operation_phase ?? "other";
    if (!current || current.phase !== phase) {
      current = { phase, operations: [op] };
      groups.push(current);
    } else {
      current.operations.push(op);
    }
  }

  return groups;
}

function formatPhaseLabel(phase: string): string {
  return phase.replace(/_/g, " ").toUpperCase();
}

function getStatusColor(status: string): string {
  switch (status.toLowerCase()) {
    case "completed":
    case "succeeded":
    case "created":
    case "successfully_imported":
      return "var(--color-create)";
    case "generated":
      return "var(--color-generated)";
    case "updated":
    case "partial":
      return "var(--color-update)";
    case "recreated":
      return "var(--color-recreate)";
    case "failed":
    case "deleted":
    case "not_imported":
      return "var(--color-delete)";
    case "destroyed":
      return "var(--color-destroyed)";
    default:
      return "var(--color-border)";
  }
}

function formatSubItemLabel(op: AdminOperationItem): string {
  if (op.operation_subtype) {
    return op.operation_subtype
      .replace(/_/g, " ")
      .replace(/\b\w/g, (c) => c.toUpperCase());
  }
  return op.operation_type
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
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

function hasArtifact(op: AdminOperationItem): boolean {
  return !!(op.artifact_type && op.blob_url);
}

export default function SessionData({
  session,
  operations,
  onReload,
  onToggleApply,
  conversationHistory,
}: SessionDataProps) {
  const [searchParams, setSearchParams] = useSearchParams();
  const operationParam = searchParams.get("operation");

  const selectedOp = useMemo(() => {
    if (!operationParam) return null;
    const opId = Number(operationParam);
    return operations.find((op) => op.id === opId && hasArtifact(op)) ?? null;
  }, [operationParam, operations]);

  const setOperationParam = useCallback(
    (op: AdminOperationItem | null) => {
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev);
        if (op) {
          next.set("operation", String(op.id));
        } else {
          next.delete("operation");
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

  const phaseGroups = groupByPhase(operations);
  const hasFailure = operations.some((op) => op.success === false);
  const started = formatShortDate(session.created_at);
  const completed = formatShortDate(session.updated_at);

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
          {session.operation_type
            ? session.operation_type.charAt(0).toUpperCase() +
              session.operation_type.slice(1)
            : "-"}
        </Typography>
      </div>
      <div className={styles.fieldRow}>
        <Typography
          variant="overline"
          component="span"
          className={styles.fieldLabel}
        >
          Cloud /Env
        </Typography>
        <Typography
          variant="body1"
          component="span"
          className={styles.fieldValue}
        >
          {session.cloud_provider} / {session.environment}
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
          <StatusBadge
            variant={
              isAdminSession(session)
                ? session.final_status || session.current_status
                : session.status
            }
          />
        </div>
      </div>

      {/* ── Admin-only Metadata ── */}
      {isAdminSession(session) && session.failure_reason && (
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
            component="span"
            className={`${styles.fieldValue} ${styles.failureValue}`}
          >
            {session.failure_reason}
          </Typography>
        </div>
      )}
      {isAdminSession(session) && session.duration_seconds != null && (
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
            {session.duration_seconds < 60
              ? `${Math.round(session.duration_seconds)}s`
              : `${Math.floor(session.duration_seconds / 60)}m ${Math.round(session.duration_seconds % 60)}s`}
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
        <div
          className={styles.timeline}
          style={
            {
              "--timeline-color": getStatusColor(session.status),
            } as React.CSSProperties
          }
        >
          {operations.length === 0 ? (
            <p className={styles.timelineEmpty}>No operations recorded</p>
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

              {/* Phase groups */}
              {phaseGroups.map((group, idx) => {
                const hasFailed = group.operations.some(
                  (op) => op.success === false,
                );

                return (
                  <div
                    key={idx}
                    className={`${styles.timelineEntry}${hasFailed ? ` ${styles.timelineEntryFailed}` : ""}`}
                  >
                    <div className={styles.timelineDot} />
                    <div className={styles.timelineContent}>
                      <span className={styles.timelinePhase}>
                        {formatPhaseLabel(group.phase)}
                      </span>
                      <Typography
                        variant="overline"
                        component="span"
                        className={styles.timelineCount}
                      >
                        {group.operations.length} OPERATION
                        {group.operations.length !== 1 ? "S" : ""}
                      </Typography>
                      <div className={styles.timelineOps}>
                        {group.operations.map((op, opIdx) => (
                          <>
                            <div
                              key={op.id}
                              className={`${styles.timelineOpRow}${opIdx === 0 ? ` ${styles.timelineOpRowFirst}` : ""}${hasArtifact(op) ? ` ${styles.timelineOpRowClickable}` : ""}`}
                              onClick={
                                hasArtifact(op)
                                  ? () => setOperationParam(op)
                                  : undefined
                              }
                              role={hasArtifact(op) ? "button" : undefined}
                              tabIndex={hasArtifact(op) ? 0 : undefined}
                              onKeyDown={
                                hasArtifact(op)
                                  ? (e) => {
                                      if (e.key === "Enter")
                                        setOperationParam(op);
                                    }
                                  : undefined
                              }
                            >
                              <Typography
                                variant="subtitle2"
                                component="span"
                                className={styles.timelineOpName}
                              >
                                {formatSubItemLabel(op)}
                              </Typography>
                              <span className={styles.timelineOpDate}>
                                {formatOpDate(op.created_at)}
                                {hasArtifact(op) && (
                                  <VisibilityIcon
                                    className={styles.artifactIcon}
                                  />
                                )}
                              </span>
                            </div>
                          </>
                        ))}
                      </div>
                    </div>
                  </div>
                );
              })}

              {/* COMPLETED / FAILED */}
              <div
                className={`${styles.timelineEntry} ${styles.timelineEntryLast}${hasFailure ? ` ${styles.timelineEntryFailed}` : ""}`}
              >
                <div className={styles.timelineDot} />
                <div className={styles.timelineContent}>
                  <span className={styles.timelinePhase}>
                    {hasFailure ? "Failed" : "Completed"}
                  </span>
                  <span className={styles.timelineDate}>{completed.date}</span>
                  <span className={styles.timelineDate}>{completed.time}</span>
                </div>
              </div>
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
          {session.iac_path && (
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
                {session.iac_path}
              </Typography>
            </div>
          )}
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
                href={session.repo_uri}
                target="_blank"
                rel="noopener noreferrer"
                className={styles.link}
              >
                Repository
                <OpenInNewIcon className={styles.linkIcon} />
              </a>
              {isAdminSession(session) && session.pull_request_url && (
                <a
                  href={session.pull_request_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className={styles.link}
                >
                  Pull Request
                  <OpenInNewIcon className={styles.linkIcon} />
                </a>
              )}
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
        {onToggleApply ? (
          <button
            type="button"
            className={
              session.apply_allowed
                ? styles.btnApplyOpenInteractive
                : styles.btnApplyInteractive
            }
            onClick={onToggleApply}
          >
            {session.apply_allowed ? (
              <LockOpenOutlinedIcon className={styles.btnIcon} />
            ) : (
              <LockOutlinedIcon className={styles.btnIcon} />
            )}
            {session.apply_allowed ? "Apply Open" : "Apply Locked"}
          </button>
        ) : (
          <span
            className={
              session.apply_allowed ? styles.btnApplyOpen : styles.btnApply
            }
          >
            {session.apply_allowed ? (
              <LockOpenOutlinedIcon className={styles.btnIcon} />
            ) : (
              <LockOutlinedIcon className={styles.btnIcon} />
            )}
            {session.apply_allowed ? "Apply Open" : "Apply Locked"}
          </span>
        )}
        {onReload && (
          <button type="button" className={styles.btnReload} onClick={onReload}>
            <ReplayIcon className={styles.btnIcon} />
            Reload Session
          </button>
        )}
      </div>

      {selectedOp && (
        <PageOverlay
          onClose={() => setOperationParam(null)}
          title={
            <span className={styles.breadcrumb}>
              <span className={styles.breadcrumbPath}>
                <span>{session.initial_query || "Session"}</span>
                <Typography
                  variant="micro"
                  component="span"
                  className={styles.breadcrumbSeparator}
                >
                  /
                </Typography>
                <span>
                  {formatPhaseLabel(selectedOp.operation_phase ?? "other")}
                </span>
              </span>
              <span className={styles.breadcrumbCurrent}>
                {formatArtifactLabel(selectedOp.artifact_type)}
              </span>
            </span>
          }
        >
          <ArtifactContent operation={selectedOp} />
        </PageOverlay>
      )}
    </div>
  );
}
