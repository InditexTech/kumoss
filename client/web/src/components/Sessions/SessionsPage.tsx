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
import { listUserSessions, getSessionDetail } from "@/services/core/sessions";
import {
  listAdminSessions,
  getAdminSessionDetail,
  setSessionLock,
} from "@/services/core/admin";
import {
  setCachedSessions,
  invalidateSessionsCache,
} from "@/services/core/sessionsCache";
import {
  resolveSessionOutcome,
  buildSessionPatch,
  buildApplyResults,
  findSessionPr,
  type SessionOutcome,
} from "@/services/workflows/session_outcome";
import type {
  AdminSessionDetail,
  OperationType,
  SessionSearchField,
  SessionStatus,
  SessionSummary,
} from "@/types/api";
import { panelRoleAtLeast } from "@/types/api";
import {
  StatusBadge,
  ProviderList,
  SideSheet,
  SessionsTable,
  truncate,
} from "@/components/ui";
import { formatDateTime } from "@/utils/datetime";
import type { ColumnDef, FilterConfig, FetchParams } from "@/components/ui";
import type { SearchFieldConfig } from "@/components/ui";
import { extractProjectName } from "./types";
import SessionData from "./SessionData/SessionData";
import styles from "./SessionsPage.module.css";

/** The session search, narrowed by what it matches (`searchIn` in the URL). */
const sessionSearch: SearchFieldConfig = {
  key: "search",
  label: "Search sessions",
  placeholder: "Search query, repository or session ID",
  scope: {
    key: "searchIn",
    label: "Search in",
    options: [
      { value: "all", label: "All fields", placeholder: "Search query, repository or session ID" },
      { value: "query", label: "Query", placeholder: "Search query text, e.g. storage account" },
      { value: "repository", label: "Repository", placeholder: "Search repository, e.g. kumossdemo" },
      { value: "session_id", label: "Session ID", placeholder: "Search session ID, e.g. 57bacc95" },
    ],
  },
};

const userSearches: SearchFieldConfig[] = [sessionSearch];

const adminSearches: SearchFieldConfig[] = [
  { key: "userSearch", label: "User email", placeholder: "Search by user email" },
  sessionSearch,
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
    render: (s) => extractProjectName(s.workspace.uri),
  },
  {
    key: "type",
    header: "Type",
    width: "8%",
    className: styles.secondaryCell,
    render: (s) => s.operation || "-",
  },
  {
    key: "providers",
    header: "Providers",
    width: "12%",
    className: styles.secondaryCell,
    render: (s) => (
      <ProviderList
        providers={(s.providers ?? []).map((p) => p.name)}
        variant="icons"
        hideUtilities
        className={styles.providerIcons}
      />
    ),
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
      s.is_blocked ? (
        <LockOutlinedIcon className={styles.applyIconLocked} />
      ) : (
        <LockOpenOutlinedIcon className={styles.applyIconOpen} />
      ),
  },
  {
    key: "created",
    header: "Created",
    width: "14%",
    className: styles.secondaryCell,
    render: (s) => formatDateTime(s.created_at),
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
      render: (s) => extractProjectName(s.workspace.uri),
    },
    {
      key: "type",
      header: "Type",
      width: "8%",
      className: styles.secondaryCell,
      render: (s) => s.operation,
    },
    {
      key: "providers",
      header: "Providers",
      width: "12%",
      className: styles.secondaryCell,
      render: (s) => (
        <ProviderList
          providers={(s.providers ?? []).map((p) => p.name)}
          variant="icons"
          hideUtilities
          className={styles.providerIcons}
        />
      ),
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
      render: (s) => formatDateTime(s.created_at),
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
      { value: "started", label: "Started", group: "In progress" },
      { value: "filtering", label: "Filtering", group: "In progress" },
      { value: "generating", label: "Generating", group: "In progress" },
      { value: "validating", label: "Validating", group: "In progress" },
      { value: "reconciling", label: "Reconciling", group: "In progress" },
      { value: "report", label: "Report", group: "In progress" },
      { value: "apply", label: "Apply", group: "In progress" },
      { value: "completed", label: "Completed", group: "Finished" },
      { value: "uncompleted", label: "Uncompleted", group: "Finished" },
      { value: "failed", label: "Failed", group: "Finished" },
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
  const { updateSession, prDetails, updatePrDetails } = useSession();
  const { setMode } = useMode();
  const { showNotification } = useNotification();
  const [searchParams, setSearchParams] = useSearchParams();
  const sessionId = searchParams.get("session");
  const [detail, setDetail] = useState<AdminSessionDetail | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [lockOverrides, setLockOverrides] = useState<Record<string, boolean>>(
    {},
  );
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
    // The admin view asks for the internal record too, as debug material;
    // the user view can only ever receive the conversation.
    const pending = isAdminView
      ? getAdminSessionDetail(sessionId, {
          includeChatHistory: true,
          includeHistory: true,
        })
      : getSessionDetail(sessionId, { includeChatHistory: true });
    pending
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
      const { page, page_size, search, searchIn, userSearch, operation, status } = params;
      const listParams = {
        page: page as number,
        page_size: page_size as number,
        search: search as string | undefined,
        search_in: searchIn as SessionSearchField | undefined,
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
          prev && prev.uuid === uuid
            ? { ...prev, is_blocked: nowBlocked }
            : prev,
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

    const operationModeMap: Record<string, "generate" | "drift" | "import"> = {
      drift: "drift",
      import: "import",
    };
    setMode(operationModeMap[detail.operation] ?? "generate");

    const patch = buildSessionPatch(outcome);

    if (outcome.kind === "apply-results") {
      updateSession({ ...patch, applyResults: buildApplyResults(outcome) });
    } else {
      updateSession(patch);
    }

    const pr = findSessionPr(outcome.detail);
    const samePr = pr != null && pr.number === prDetails.number;
    updatePrDetails(
      pr
        ? {
            number: pr.number,
            url: pr.url,
            merged: samePr ? prDetails.merged : undefined,
            lastPrStep: samePr ? prDetails.lastPrStep : undefined,
          }
        : {
            number: undefined,
            url: undefined,
            merged: undefined,
            lastPrStep: undefined,
          },
    );

    handleCloseOverlay();
    void navigate(
      outcome.kind === "apply-results"
        ? `/home/apply-results/${detail.uuid}`
        : `/home/results/${detail.uuid}`,
    );
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
              detail.current_status !== "failed"
                ? () => void handleReload()
                : undefined
            }
            onToggleLock={
              canToggleLock
                ? () => void handleToggleLock(detail.uuid, detail.is_blocked)
                : undefined
            }
          />
        ) : null}
      </SideSheet>
    </div>
  );
}
