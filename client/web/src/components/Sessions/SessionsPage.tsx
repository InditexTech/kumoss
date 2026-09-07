// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { useState, useEffect, useCallback, useMemo } from "react";
import type { ReactNode } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { IconButton } from "@mui/material";
import LockOpenOutlinedIcon from "@mui/icons-material/LockOpenOutlined";
import LockOutlinedIcon from "@mui/icons-material/LockOutlined";
import OpenInNewIcon from "@mui/icons-material/OpenInNew";
import { useAuth } from "@/contexts/AuthContext";
import { useSession } from "@/contexts/SessionContext";
import { useMode } from "@/contexts/ModeContext";
import { useNotification } from "@/contexts/NotificationContext";
import { getApiErrorMessage } from "@/services/api";
import {
  listUserSessions,
  getSessionDetail,
} from "@/services/core/sessions";
import {
  listAdminSessions,
  getAdminSessionDetail,
  setSessionLock,
} from "@/services/core/admin";
import { setCachedSessions, invalidateSessionsCache } from "@/services/core/sessionsCache";
import {
  resolveSessionOutcome,
  buildSessionPatch,
  buildApplyResults,
  buildAssistantMessage,
  type SessionOutcome,
} from "@/services/workflows/session_outcome";
import type {
  OperationType,
  SessionDetail,
  SessionStatus,
  SessionSummary,
} from "@/types/api";
import { normalizeHistory, panelRoleAtLeast } from "@/types/api";
import { providerLabel } from "@/constants/providers";
import {
  StatusBadge,
  SideSheet,
  SessionsTable,
  formatDate,
  truncate,
} from "@/components/ui";
import type { ColumnDef, FilterConfig, FetchParams } from "@/components/ui";
import type { SearchFieldConfig } from "@/components/ui";
import { extractProjectName } from "./types";
import SessionData from "./SessionData/SessionData";
import styles from "./SessionsPage.module.css";

const SEARCH_PLACEHOLDER = "Search by project name, query or session id";

const userSearches: SearchFieldConfig[] = [
  { key: "search", placeholder: SEARCH_PLACEHOLDER },
];

const adminSearches: SearchFieldConfig[] = [
  { key: "userSearch", placeholder: "Search by user email" },
  { key: "search", placeholder: SEARCH_PLACEHOLDER },
];

const baseColumns: ColumnDef<SessionSummary>[] = [
  {
    key: "query",
    header: "Query",
    width: "34%",
    render: (s) => (
      <span title={s.first_query || ""}>{truncate(s.first_query)}</span>
    ),
  },
  {
    key: "project",
    header: "Project",
    width: "16%",
    className: styles.secondaryCell,
    render: (s) => extractProjectName(s.workspace_uri),
  },
  {
    key: "type",
    header: "Type",
    width: "8%",
    className: styles.secondaryCell,
    render: (s) => s.operation || "-",
  },
  {
    key: "cloud",
    header: "Cloud",
    width: "12%",
    className: styles.secondaryCell,
    render: (s) => providerLabel(s.provider),
  },
  {
    key: "status",
    header: "Status",
    width: "10%",
    render: (s) => <StatusBadge variant={s.current_status} />,
  },
  {
    key: "apply",
    header: "Apply",
    width: "6%",
    className: styles.applyCell,
    render: (s) =>
      s.operation === "generate" || s.operation === "import" ? (
        s.is_blocked ? (
          <LockOutlinedIcon className={styles.applyIconLocked} />
        ) : (
          <LockOpenOutlinedIcon className={styles.applyIconOpen} />
        )
      ) : null,
  },
  {
    key: "created",
    header: "Created",
    width: "14%",
    className: styles.secondaryCell,
    render: (s) => formatDate(s.created_at),
  },
];

function buildAdminColumns(
  renderApply: (s: SessionSummary) => ReactNode,
): ColumnDef<SessionSummary>[] {
  return [
    {
      key: "user",
      header: "User",
      width: "12%",
      render: (s) => (s.username ? s.username.split("@")[0] : "-"),
    },
    {
      key: "id",
      header: "Session ID",
      width: "10%",
      className: styles.secondaryCell,
      render: (s) => <span title={s.uuid}>{s.uuid.slice(0, 8)}</span>,
    },
    {
      key: "query",
      header: "Query",
      width: "18%",
      render: (s) => (
        <span title={s.first_query || ""}>{truncate(s.first_query)}</span>
      ),
    },
    {
      key: "project",
      header: "Project",
      width: "14%",
      className: styles.secondaryCell,
      render: (s) => extractProjectName(s.workspace_uri),
    },
    {
      key: "type",
      header: "Type",
      width: "8%",
      className: styles.secondaryCell,
      render: (s) => s.operation,
    },
    {
      key: "cloud",
      header: "Cloud",
      width: "12%",
      className: styles.secondaryCell,
      render: (s) => providerLabel(s.provider),
    },
    {
      key: "status",
      header: "Status",
      width: "8%",
      render: (s) => <StatusBadge variant={s.current_status} />,
    },
    {
      key: "apply",
      header: "Apply",
      width: "5%",
      className: styles.applyCell,
      render: renderApply,
    },
    {
      key: "created",
      header: "Created",
      width: "13%",
      className: styles.secondaryCell,
      render: (s) => formatDate(s.created_at),
    },
  ];
}

const filters: FilterConfig[] = [
  {
    key: "operation",
    placeholder: "TYPE",
    options: [
      { value: "generate", label: "Generate" },
      { value: "drift", label: "Drift" },
      { value: "import", label: "Import" },
    ],
  },
  {
    key: "status",
    placeholder: "STATUS",
    options: [
      { value: "generating", label: "Generating" },
      { value: "completed", label: "Completed" },
      { value: "uncompleted", label: "Uncompleted" },
      { value: "failed", label: "Failed" },
    ],
  },
];

interface SessionsPageProps {
  variant?: "user" | "admin";
}

export default function SessionsPage({ variant = "user" }: SessionsPageProps) {
  const isAdminView = variant === "admin";
  const { panelRole } = useAuth();
  const navigate = useNavigate();
  const { updateSession } = useSession();
  const { setMode } = useMode();
  const { showNotification } = useNotification();
  const [searchParams, setSearchParams] = useSearchParams();
  const sessionId = searchParams.get("session");
  const [detail, setDetail] = useState<SessionDetail | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [lockOverrides, setLockOverrides] = useState<Record<string, boolean>>({});
  const canToggleLock = isAdminView && panelRoleAtLeast(panelRole, "editor");

  const setSessionParam = useCallback(
    (id: string | null) => {
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev);
        if (id) {
          next.set("session", id);
        } else {
          next.delete("session");
          next.delete("artifact");
          next.delete("detail");
          next.delete("resource");
          next.delete("filter");
          next.delete("file");
        }
        return next;
      });
    },
    [setSearchParams],
  );

  useEffect(() => {
    if (!sessionId) {
      setDetail(null);
      setLoadingDetail(false);
      return;
    }
    if (detail?.uuid === sessionId) return;

    let cancelled = false;
    setLoadingDetail(true);
    const fetchDetail = isAdminView ? getAdminSessionDetail : getSessionDetail;
    fetchDetail(sessionId, { includeHistory: true })
      .then((d) => {
        if (!cancelled) setDetail(d);
      })
      .catch((err) => {
        if (!cancelled) {
          showNotification(
            "failure",
            `Failed to load session detail: ${getApiErrorMessage(err)}`,
          );
          setSessionParam(null);
        }
      })
      .finally(() => {
        if (!cancelled) setLoadingDetail(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  const fetchSessions = useCallback(
    async (params: FetchParams) => {
      const { page, page_size, search, userSearch, operation, status } = params;
      const listParams = {
        page: page as number,
        page_size: page_size as number,
        search: search as string | undefined,
        status: status as SessionStatus | undefined,
        operation: operation as OperationType | undefined,
      };
      const data = isAdminView
        ? await listAdminSessions({
            ...listParams,
            user_email: (userSearch as string) || undefined,
          })
        : await listUserSessions(listParams);
      if (!isAdminView && page === 1 && !search && !status && !operation) {
        setCachedSessions(data.items, data.total);
      }
      setLockOverrides({});
      return data;
    },
    [isAdminView],
  );

  const handleToggleLock = useCallback(
    async (uuid: string, blocked: boolean) => {
      try {
        const res = await setSessionLock(uuid, !blocked);
        const nowBlocked = res.is_blocked;
        setLockOverrides((prev) => ({ ...prev, [uuid]: nowBlocked }));
        setDetail((prev) =>
          prev && prev.uuid === uuid ? { ...prev, is_blocked: nowBlocked } : prev,
        );
      } catch (err) {
        showNotification(
          "failure",
          `Failed to update the apply lock: ${getApiErrorMessage(err)}`,
        );
      }
    },
    [showNotification],
  );

  const adminColumns = useMemo(
    () =>
      buildAdminColumns((s) => {
        if (s.operation !== "generate" && s.operation !== "import") return null;
        const blocked = lockOverrides[s.uuid] ?? s.is_blocked;
        const icon = blocked ? (
          <LockOutlinedIcon className={styles.applyIconLocked} />
        ) : (
          <LockOpenOutlinedIcon className={styles.applyIconOpen} />
        );
        if (!canToggleLock) return icon;
        return (
          <IconButton
            size="small"
            aria-label={blocked ? "Unlock apply" : "Lock apply"}
            onClick={(e) => {
              e.stopPropagation();
              void handleToggleLock(s.uuid, blocked);
            }}
          >
            {icon}
          </IconButton>
        );
      }),
    [lockOverrides, canToggleLock, handleToggleLock],
  );

  function handleRowClick(row: SessionSummary) {
    setSessionParam(row.uuid);
  }

  async function handleReload() {
    if (!detail) return;
    invalidateSessionsCache();

    let outcome: SessionOutcome;
    try {
      outcome = await resolveSessionOutcome(detail);
    } catch (err) {
      showNotification(
        "failure",
        `Failed to load session results: ${getApiErrorMessage(err)}`,
      );
      return;
    }
    if (outcome.kind === "failed") {
      showNotification("failure", outcome.message);
      return;
    }

    setMode(
      detail.operation === "drift"
        ? "drift"
        : outcome.kind === "apply-results"
          ? "import"
          : "generate",
    );

    const patch = buildSessionPatch(outcome);

    if (outcome.kind === "apply-results") {
      updateSession({ ...patch, applyResults: buildApplyResults(outcome) });
      handleCloseOverlay();
      navigate(`/home/apply-results/${detail.uuid}`);
      return;
    }

    if (outcome.kind === "rejected") {
      updateSession({
        ...patch,
        full_history: [
          ...(patch.full_history ?? []),
          {
            role: "assistant" as const,
            content: buildAssistantMessage(outcome),
          },
        ],
      });
    } else {
      updateSession(patch);
    }
    handleCloseOverlay();
    navigate(`/home/results/${detail.uuid}`);
  }

  function handleCloseOverlay() {
    setSessionParam(null);
  }

  return (
    <div className={styles.wrapper}>
      <SessionsTable<SessionSummary>
        columns={isAdminView ? adminColumns : baseColumns}
        fetchData={fetchSessions}
        filters={filters}
        rowKey={(s) => s.uuid}
        searches={isAdminView ? adminSearches : userSearches}
        onRowClick={handleRowClick}
        extraToolbarContent={
          isAdminView ? (
            <a
              href="/monitoring/projects"
              target="_blank"
              rel="noopener noreferrer"
              className={styles.phoenixLink}
            >
              <OpenInNewIcon style={{ fontSize: "14px" }} />
              Phoenix
            </a>
          ) : undefined
        }
      />

      <SideSheet
        isVisible={!!sessionId}
        onClose={handleCloseOverlay}
        title={detail?.first_query || "Session Detail"}
      >
        {loadingDetail ? (
          <p>Loading...</p>
        ) : detail ? (
          <SessionData
            session={detail}
            onReload={
              detail.current_status !== "failed" ? handleReload : undefined
            }
            onToggleLock={
              canToggleLock
                ? () => void handleToggleLock(detail.uuid, detail.is_blocked)
                : undefined
            }
            conversationHistory={
              isAdminView && detail.history
                ? normalizeHistory(detail.history)
                : undefined
            }
          />
        ) : null}
      </SideSheet>
    </div>
  );
}
