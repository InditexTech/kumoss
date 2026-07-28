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
import {
  listUserSessions,
  getSession,
  getSessionOperations,
  fetchArtifactContent,
} from "@/services/core/sessions";
import {
  listSessions as listAdminSessions,
  getSessionDetail,
  toggleApplyAllowed,
} from "@/services/core/admin";
import { setCachedSessions, invalidateSessionsCache } from "@/services/core/sessionsCache";
import type { TerraformReport } from "@/types";
import type {
  UserSessionInfo,
  AdminSessionInfo,
  AdminOperationItem,
  HistoryEntry,
} from "@/types/api";
import {
  StatusBadge,
  SideSheet,
  SessionsTable,
  formatDate,
  truncate,
} from "@/components/ui";
import type { ColumnDef, FilterConfig, FetchParams } from "@/components/ui";
import type { SessionItem } from "./types";
import { extractProjectName } from "./types";
import type { SearchFieldConfig } from "@/components/ui";
import SessionData from "./SessionData/SessionData";
import styles from "./SessionsPage.module.css";

const userSearches: SearchFieldConfig[] = [
  { key: "search", placeholder: "Search by project name or query" },
];

const adminSearches: SearchFieldConfig[] = [
  { key: "userSearch", placeholder: "Search by user email" },
  { key: "search", placeholder: "Search by project name or query" },
];

const columns: ColumnDef<UserSessionInfo>[] = [
  {
    key: "query",
    header: "Query",
    width: "35%",
    render: (s) => (
      <span title={s.initial_query || ""}>
        {truncate(s.initial_query ?? null)}
      </span>
    ),
  },
  {
    key: "project",
    header: "Project",
    width: "16%",
    className: styles.secondaryCell,
    render: (s) => extractProjectName(s.repo_uri),
  },
  {
    key: "type",
    header: "Type",
    width: "8%",
    className: styles.secondaryCell,
    render: (s) => s.operation_type || "-",
  },
  {
    key: "cloud",
    header: "Cloud",
    width: "8%",
    className: styles.secondaryCell,
    render: (s) => s.cloud_provider,
  },
  {
    key: "env",
    header: "Env",
    width: "8%",
    className: styles.secondaryCell,
    render: (s) => s.environment,
  },
  {
    key: "status",
    header: "Status",
    width: "8%",
    render: (s) => <StatusBadge variant={s.status} />,
  },
  {
    key: "apply",
    header: "Apply",
    width: "5%",
    className: styles.applyCell,
    render: (s) =>
      s.operation_type === "generate" ? (
        s.apply_allowed ? (
          <LockOpenOutlinedIcon className={styles.applyIconOpen} />
        ) : (
          <LockOutlinedIcon className={styles.applyIconLocked} />
        )
      ) : null,
  },
  {
    key: "created",
    header: "Created",
    width: "12%",
    className: styles.secondaryCell,
    render: (s) => formatDate(s.created_at),
  },
];

const adminColumns: ColumnDef<AdminSessionInfo>[] = [
  {
    key: "user",
    header: "Usuario",
    width: "13%",
    render: (s) => s.user_id.split("@")[0],
  },
  {
    key: "query",
    header: "Query",
    width: "28%",
    render: (s) => (
      <span title={s.initial_query || ""}>
        {truncate(s.initial_query)}
      </span>
    ),
  },
  {
    key: "project",
    header: "Project",
    width: "13%",
    className: styles.secondaryCell,
    render: (s) =>
      s.repository_id ? s.repository_id.replace(/_[^_]+$/, "") : "-",
  },
  {
    key: "type",
    header: "Type",
    width: "8%",
    className: styles.secondaryCell,
    render: (s) => s.operation_type,
  },
  {
    key: "cloud",
    header: "Cloud",
    width: "8%",
    className: styles.secondaryCell,
    render: (s) => s.cloud_provider,
  },
  {
    key: "env",
    header: "Env",
    width: "8%",
    className: styles.secondaryCell,
    render: (s) => s.environment,
  },
  {
    key: "status",
    header: "Status",
    width: "8%",
    render: (s) => <StatusBadge variant={s.final_status || s.current_status} />,
  },
  {
    key: "apply",
    header: "Apply",
    width: "5%",
    className: styles.applyCell,
    render: (s) =>
      s.operation_type === "generate" || s.operation_type === "import" ? (
        s.apply_allowed ? (
          <LockOpenOutlinedIcon className={styles.applyIconOpen} />
        ) : (
          <LockOutlinedIcon className={styles.applyIconLocked} />
        )
      ) : null,
  },
  {
    key: "created",
    header: "Created",
    width: "9%",
    className: styles.secondaryCell,
    render: (s) => formatDate(s.created_at),
  },
];

const filters: FilterConfig[] = [
  {
    key: "operationType",
    placeholder: "TYPE",
    options: [
      { value: "generate", label: "Generate" },
      { value: "apply", label: "Apply" },
      { value: "import", label: "Import" },
      { value: "drift", label: "Drift" },
    ],
  },
  {
    key: "status",
    placeholder: "STATUS",
    options: [
      { value: "generating", label: "Generating" },
      { value: "completed", label: "Completed" },
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
  const username = user?.username || "";
  const [searchParams, setSearchParams] = useSearchParams();
  const sessionId = searchParams.get("session");
  const [selectedSession, setSelectedSession] = useState<SessionItem | null>(null);
  const [operations, setOperations] = useState<AdminOperationItem[]>([]);
  const [conversationHistory, setConversationHistory] = useState<HistoryEntry[]>([]);
  const [loadingDetail, setLoadingDetail] = useState(false);

  const setSessionParam = useCallback(
    (id: string | null) => {
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev);
        if (id) {
          next.set("session", id);
        } else {
          next.delete("session");
          next.delete("operation");
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
      setSelectedSession(null);
      setOperations([]);
      setConversationHistory([]);
      setLoadingDetail(false);
      return;
    }
    if (selectedSession?.session_id === sessionId) return;

    let cancelled = false;
    setLoadingDetail(true);

    (async () => {
      try {
        if (isAdminView) {
          const detail = await getSessionDetail(sessionId);
          if (cancelled) return;
          setSelectedSession(detail.session);
          setOperations(detail.operations);
          setConversationHistory(detail.full_history ?? []);
        } else {
          const [session, ops] = await Promise.all([
            getSession(sessionId),
            getSessionOperations(sessionId),
          ]);
          if (cancelled) return;
          setSelectedSession(session);
          setOperations(ops);
          setConversationHistory([]);
        }
      } catch {
        if (cancelled) return;
        setSessionParam(null);
      } finally {
        if (!cancelled) setLoadingDetail(false);
      }
    })();

    return () => { cancelled = true; };
  }, [sessionId, isAdminView]);

  const fetchUserSessions = useCallback(
    async (
      params: FetchParams,
    ): Promise<{ items: UserSessionInfo[]; total: number; page: number; page_size: number; total_pages?: number }> => {
      const { page, page_size, search, operationType, status } = params;
      const data = await listUserSessions(username, {
        page: page as number,
        page_size: page_size as number,
        search: search as string | undefined,
        status: status as string | undefined,
        operation_type: operationType as string | undefined,
      });
      if (page === 1 && !search && !status && !operationType) {
        setCachedSessions(data.items, data.total);
      }
      return data;
    },
    [username],
  );

  const fetchAdminSessions = useCallback(
    async (
      params: FetchParams,
    ): Promise<{ items: AdminSessionInfo[]; total: number; page: number; page_size: number; total_pages?: number }> => {
      return listAdminSessions(params);
    },
    [],
  );

  function handleRowClick(row: SessionItem) {
    setSessionParam(row.session_id);
  }

  async function handleToggleApply() {
    if (!selectedSession) return;
    const result = await toggleApplyAllowed(
      selectedSession.session_id,
      !selectedSession.apply_allowed,
    );
    setSelectedSession((prev) =>
      prev ? { ...prev, apply_allowed: result.apply_allowed } : null,
    );
  }

  async function handleReload() {
    if (!selectedSession) return;
    invalidateSessionsCache();

    const reportOp = operations.find(
      (op) => op.artifact_type === "terraform_report" && op.blob_url,
    );
    const codeOp = operations.find(
      (op) => op.artifact_type === "generated_code" && op.blob_url,
    );

    const [reportContent, codeContent] = await Promise.all([
      reportOp?.blob_url
        ? fetchArtifactContent(reportOp.blob_url)
        : Promise.resolve(null),
      codeOp?.blob_url
        ? fetchArtifactContent(codeOp.blob_url)
        : Promise.resolve(null),
    ]);

    let report: TerraformReport | undefined;
    if (reportContent) {
      try {
        report = JSON.parse(reportContent);
      } catch {
        // ignore malformed report
      }
    }

    const opType = selectedSession.operation_type;
    if (opType === "apply") setMode("import");
    else if (opType === "drift") setMode("drift");
    else setMode("generate");

    updateSession({
      session_id: selectedSession.session_id,
      cloud: selectedSession.cloud_provider,
      environment: selectedSession.environment,
      branchName: selectedSession.branch_name,
      repositoryUrl: selectedSession.repo_uri,
      terraform_report: report,
      apply_allowed: selectedSession.apply_allowed,
    });

    const isApply = opType === "apply" || opType === "import";

    if (isApply) {
      updateSession({
        applyResults: {
          sessionId: selectedSession.session_id,
          status: report?.status ?? "Unknown",
          message: report?.execution_summary ?? "",
          errorMessage: "",
          timestamp: new Date().toISOString(),
          applyReport: report ?? null,
        },
      });
      handleCloseOverlay();
      navigate(`/home/apply-results/${selectedSession.session_id}`);
    } else {
      updateSession({ code: codeContent ?? "" });
      handleCloseOverlay();
      navigate(`/home/results/${selectedSession.session_id}`);
    }
  }

  function handleCloseOverlay() {
    setSessionParam(null);
  }

  return (
    <div className={styles.wrapper}>
      {isAdminView ? (
        <SessionsTable<AdminSessionInfo>
          columns={adminColumns}
          fetchData={fetchAdminSessions}
          filters={filters}
          rowKey={(s) => s.session_id}
          searches={adminSearches}
          onRowClick={handleRowClick}
          extraToolbarContent={
            <a
              href="/monitoring/projects"
              target="_blank"
              rel="noopener noreferrer"
              className={styles.phoenixLink}
            >
              <OpenInNewIcon style={{ fontSize: "14px" }} />
              Phoenix
            </a>
          }
        />
      ) : (
        <SessionsTable<UserSessionInfo>
          columns={columns}
          fetchData={fetchUserSessions}
          filters={filters}
          rowKey={(s) => s.session_id}
          searches={userSearches}
          onRowClick={handleRowClick}
        />
      )}

      <SideSheet
        isVisible={!!sessionId}
        onClose={handleCloseOverlay}
        title={selectedSession?.initial_query || "Session Detail"}
      >
        {loadingDetail ? (
          <p>Loading...</p>
        ) : selectedSession ? (
          <SessionData
            session={selectedSession}
            operations={operations}
            onReload={handleReload}
            onToggleApply={isAdminView ? handleToggleApply : undefined}
            conversationHistory={isAdminView ? conversationHistory : undefined}
          />
        ) : null}
      </SideSheet>
    </div>
  );
}
