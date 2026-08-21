// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { useState, useEffect, useCallback } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
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
import { normalizeHistory } from "@/types/api";
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

const userSearches: SearchFieldConfig[] = [
  { key: "search", placeholder: "Search by project name or query" },
];

const adminSearches: SearchFieldConfig[] = [
  { key: "userSearch", placeholder: "Search by user email" },
  { key: "search", placeholder: "Search by project name or query" },
];

const baseColumns: ColumnDef<SessionSummary>[] = [
  {
    key: "query",
    header: "Query",
    width: "38%",
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
    width: "8%",
    className: styles.secondaryCell,
    render: (s) => s.provider,
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

const adminColumns: ColumnDef<SessionSummary>[] = [
  {
    key: "user",
    header: "User",
    width: "12%",
    render: (s) => (s.username ? s.username.split("@")[0] : "-"),
  },
  {
    key: "query",
    header: "Query",
    width: "30%",
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
    width: "8%",
    className: styles.secondaryCell,
    render: (s) => s.provider,
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
    width: "15%",
    className: styles.secondaryCell,
    render: (s) => formatDate(s.created_at),
  },
];

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
  const { user } = useAuth();
  const navigate = useNavigate();
  const { updateSession } = useSession();
  const { setMode } = useMode();
  const { showNotification } = useNotification();
  const username = user?.username || "";
  const [searchParams, setSearchParams] = useSearchParams();
  const sessionId = searchParams.get("session");
  const [detail, setDetail] = useState<SessionDetail | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);

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
    getSessionDetail(sessionId, { includeHistory: true })
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
      // The admin view can scope the listing to another user by email;
      // it falls back to the current user until cross-user admin
      // endpoints exist again server-side.
      const email = isAdminView ? (userSearch as string) || username : username;
      const data = await listUserSessions(email, {
        page: page as number,
        page_size: page_size as number,
        search: search as string | undefined,
        status: status as SessionStatus | undefined,
        operation: operation as OperationType | undefined,
      });
      if (!isAdminView && page === 1 && !search && !status && !operation) {
        setCachedSessions(data.items, data.total);
      }
      return data;
    },
    [username, isAdminView],
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
