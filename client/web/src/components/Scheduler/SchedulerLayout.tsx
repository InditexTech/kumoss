// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { useState, useEffect, useCallback } from "react";
import { useSearchParams } from "react-router-dom";
import {
  Button,
  TextField,
  Select,
  MenuItem,
  FormControl,
  InputLabel,
  Switch,
  FormControlLabel,
} from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import { useAuth } from "@/contexts/AuthContext";
import { useNotification } from "@/contexts/NotificationContext";
import { getApiErrorMessage } from "@/services/api";
import {
  listSchedules,
  getSchedule,
  createSchedule,
  updateSchedule,
  deleteSchedule,
} from "@/services/core/schedules";
import { listOperations } from "@/services/core/operations";
import { StatusBadge, SideSheet, SessionsTable, formatDate } from "@/components/ui";
import type { ColumnDef, FilterConfig, FetchParams } from "@/components/ui";
import type {
  Schedule,
  ScheduleKind,
  ScheduleOperation,
  CreateScheduleRequest,
  UpdateScheduleRequest,
} from "@/types/api_scheduler";
import { panelRoleAtLeast } from "@/types/api";
import styles from "./SchedulerLayout.module.css";

const KIND_LABELS: Record<ScheduleKind, string> = {
  GENERATE: "Generate",
  DRIFT: "Drift",
  APPLY: "Apply",
  IMPORT: "Import",
};

const columns: ColumnDef<Schedule>[] = [
  {
    key: "name",
    header: "Name",
    width: "24%",
    render: (s) => s.name,
  },
  {
    key: "kind",
    header: "Kind",
    width: "10%",
    className: styles.secondaryCell,
    render: (s) => KIND_LABELS[s.kind] ?? s.kind,
  },
  {
    key: "cron",
    header: "Cron",
    width: "14%",
    className: styles.secondaryCell,
    render: (s) => s.cron,
  },
  {
    key: "enabled",
    header: "Enabled",
    width: "8%",
    className: styles.enabledCell,
    render: (s) => (
      <span
        className={`${styles.enabledDot} ${s.enabled ? styles.enabledDotOn : styles.enabledDotOff}`}
        title={s.enabled ? "Enabled" : "Disabled"}
      />
    ),
  },
  {
    key: "next_run",
    header: "Next Run",
    width: "16%",
    className: styles.secondaryCell,
    render: (s) => formatDate(s.next_run_at),
  },
  {
    key: "last_run",
    header: "Last Run",
    width: "16%",
    className: styles.secondaryCell,
    render: (s) => formatDate(s.last_run_at),
  },
  {
    key: "created",
    header: "Created",
    width: "12%",
    className: styles.secondaryCell,
    render: (s) => formatDate(s.created_at),
  },
];

const filters: FilterConfig[] = [
  {
    key: "kind",
    placeholder: "KIND",
    options: [
      { value: "GENERATE", label: "Generate" },
      { value: "DRIFT", label: "Drift" },
      { value: "APPLY", label: "Apply" },
      { value: "IMPORT", label: "Import" },
    ],
  },
];

type ViewMode = "list" | "detail" | "form";

export default function SchedulerLayout() {
  const { panelRole, user } = useAuth();
  const { showNotification } = useNotification();
  const [searchParams, setSearchParams] = useSearchParams();
  const scheduleId = searchParams.get("schedule");

  const [detail, setDetail] = useState<Schedule | null>(null);
  const [operations, setOperations] = useState<ScheduleOperation[]>([]);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [viewMode, setViewMode] = useState<ViewMode>("list");
  const [editingSchedule, setEditingSchedule] = useState<Schedule | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  const isAdmin = panelRoleAtLeast(panelRole, "admin");

  const setScheduleParam = useCallback(
    (id: string | null) => {
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev);
        if (id) {
          next.set("schedule", id);
        } else {
          next.delete("schedule");
        }
        return next;
      });
    },
    [setSearchParams],
  );

  useEffect(() => {
    if (!scheduleId) {
      setDetail(null);
      setOperations([]);
      setLoadingDetail(false);
      setViewMode("list");
      return;
    }
    if (detail?.uuid === scheduleId) return;

    let cancelled = false;
    setLoadingDetail(true);

    Promise.all([
      getSchedule(scheduleId),
      listOperations({ schedule_uuid: scheduleId, page: 1, page_size: 50 }),
    ])
      .then(([sched, ops]) => {
        if (cancelled) return;
        setDetail(sched);
        setOperations(ops.items);
        setViewMode("detail");
      })
      .catch((err) => {
        if (cancelled) return;
        showNotification(
          "failure",
          `Failed to load schedule: ${getApiErrorMessage(err)}`,
        );
        setScheduleParam(null);
      })
      .finally(() => {
        if (!cancelled) setLoadingDetail(false);
      });

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scheduleId]);

  const fetchSchedules = useCallback(async (params: FetchParams) => {
    const { page, page_size } = params;
    return listSchedules({
      page: page as number,
      page_size: page_size as number,
    });
  }, []);

  function handleRowClick(row: Schedule) {
    setScheduleParam(row.uuid);
  }

  function handleCloseOverlay() {
    setScheduleParam(null);
    setViewMode("list");
    setEditingSchedule(null);
  }

  function handleCreate() {
    setEditingSchedule(null);
    setViewMode("form");
  }

  function handleEdit() {
    if (detail) {
      setEditingSchedule(detail);
      setViewMode("form");
    }
  }

  async function handleDelete() {
    if (!detail) return;
    try {
      await deleteSchedule(detail.uuid);
      showNotification("success", "Schedule deleted");
      handleCloseOverlay();
      setRefreshKey((k) => k + 1);
    } catch (err) {
      showNotification(
        "failure",
        `Failed to delete schedule: ${getApiErrorMessage(err)}`,
      );
    }
  }

  async function handleFormSubmit(data: CreateScheduleRequest | UpdateScheduleRequest) {
    try {
      if (editingSchedule) {
        await updateSchedule(editingSchedule.uuid, data as UpdateScheduleRequest);
        showNotification("success", "Schedule updated");
      } else {
        await createSchedule(data as CreateScheduleRequest);
        showNotification("success", "Schedule created");
      }
      handleCloseOverlay();
      setRefreshKey((k) => k + 1);
    } catch (err) {
      showNotification(
        "failure",
        `Failed to save schedule: ${getApiErrorMessage(err)}`,
      );
    }
  }

  if (!isAdmin) {
    return (
      <div className={styles.wrapper}>
        <p>You need admin privileges to access the scheduler.</p>
      </div>
    );
  }

  return (
    <div className={styles.wrapper}>
      <SessionsTable<Schedule>
        key={refreshKey}
        columns={columns}
        fetchData={fetchSchedules}
        filters={filters}
        rowKey={(s) => s.uuid}
        onRowClick={handleRowClick}
        emptyText="No schedules found"
        extraToolbarContent={
          <Button
            size="small"
            startIcon={<AddIcon />}
            onClick={handleCreate}
            sx={{
              fontSize: 12,
              fontWeight: 500,
              textTransform: "uppercase",
              letterSpacing: "0.04em",
            }}
          >
            New Schedule
          </Button>
        }
      />

      {/* Detail side sheet */}
      <SideSheet
        isVisible={viewMode === "detail" && !!scheduleId}
        onClose={handleCloseOverlay}
        title={detail?.name || "Schedule Detail"}
      >
        {loadingDetail ? (
          <p>Loading...</p>
        ) : detail ? (
          <ScheduleDetail
            schedule={detail}
            operations={operations}
            onEdit={handleEdit}
            onDelete={handleDelete}
          />
        ) : null}
      </SideSheet>

      {/* Form side sheet */}
      <SideSheet
        isVisible={viewMode === "form"}
        onClose={handleCloseOverlay}
        title={editingSchedule ? "Edit Schedule" : "New Schedule"}
      >
        <ScheduleForm
          schedule={editingSchedule}
          userEmail={user?.email ?? ""}
          onSubmit={handleFormSubmit}
          onCancel={handleCloseOverlay}
        />
      </SideSheet>
    </div>
  );
}

function ScheduleDetail({
  schedule,
  operations,
  onEdit,
  onDelete,
}: {
  schedule: Schedule;
  operations: ScheduleOperation[];
  onEdit: () => void;
  onDelete: () => void;
}) {
  return (
    <>
      <div className={styles.detailSection}>
        <div className={styles.detailGrid}>
          <span className={styles.detailLabel}>Kind</span>
          <span className={styles.detailValue}>
            {KIND_LABELS[schedule.kind] ?? schedule.kind}
          </span>
          <span className={styles.detailLabel}>Cron</span>
          <span className={styles.detailValue}>{schedule.cron}</span>
          <span className={styles.detailLabel}>Enabled</span>
          <span className={styles.detailValue}>
            {schedule.enabled ? "Yes" : "No"}
          </span>
          <span className={styles.detailLabel}>User</span>
          <span className={styles.detailValue}>{schedule.user_id ?? "-"}</span>
          <span className={styles.detailLabel}>Next Run</span>
          <span className={styles.detailValue}>
            {formatDate(schedule.next_run_at)}
          </span>
          <span className={styles.detailLabel}>Last Run</span>
          <span className={styles.detailValue}>
            {formatDate(schedule.last_run_at)}
          </span>
          <span className={styles.detailLabel}>Created</span>
          <span className={styles.detailValue}>
            {formatDate(schedule.created_at)}
          </span>
          <span className={styles.detailLabel}>Params</span>
          <span className={styles.detailValue}>
            {Object.keys(schedule.params).length > 0
              ? JSON.stringify(schedule.params, null, 2)
              : "-"}
          </span>
        </div>

        <div className={styles.actions}>
          <Button variant="outlined" size="small" onClick={onEdit}>
            Edit
          </Button>
          <Button
            variant="outlined"
            size="small"
            color="error"
            onClick={onDelete}
          >
            Delete
          </Button>
        </div>
      </div>

      <div className={styles.detailSection}>
        <div className={styles.sectionTitle}>Operations History</div>
        {operations.length === 0 ? (
          <p style={{ fontSize: 13, opacity: 0.6 }}>No operations yet</p>
        ) : (
          <div className={styles.operationsList}>
            {operations.map((op) => (
              <div key={op.uuid} className={styles.operationCard}>
                <div className={styles.operationRow}>
                  <span>{KIND_LABELS[op.kind] ?? op.kind}</span>
                  <StatusBadge variant={op.status} />
                </div>
                <div className={styles.operationRow}>
                  <span style={{ opacity: 0.6 }}>
                    {formatDate(op.scheduled_at)}
                  </span>
                  <span style={{ opacity: 0.6 }}>
                    Attempt {op.attempt}/{op.max_attempts}
                  </span>
                </div>
                {op.error && (
                  <div className={styles.operationError}>{op.error}</div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </>
  );
}

function ScheduleForm({
  schedule,
  userEmail,
  onSubmit,
  onCancel,
}: {
  schedule: Schedule | null;
  userEmail: string;
  onSubmit: (data: CreateScheduleRequest | UpdateScheduleRequest) => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState(schedule?.name ?? "");
  const [kind, setKind] = useState<ScheduleKind>(schedule?.kind ?? "DRIFT");
  const [cron, setCron] = useState(schedule?.cron ?? "");
  const [enabled, setEnabled] = useState(schedule?.enabled ?? true);
  const [repoUri, setRepoUri] = useState(
    (schedule?.params?.repo_uri as string) ?? "",
  );
  const [terraformProvider, setTerraformProvider] = useState(
    (schedule?.params?.terraform_providers as string) ?? "",
  );
  const [query, setQuery] = useState(
    (schedule?.params?.q as string) ?? "",
  );
  const [iacPath, setIacPath] = useState(
    (schedule?.params?.iac_path as string) ?? ".",
  );
  const [scopeId, setScopeId] = useState(
    (schedule?.params?.scope_id as string) ?? "",
  );

  function buildParams(): Record<string, unknown> {
    return {
      repo_uri: repoUri,
      terraform_providers: terraformProvider,
      q: query,
      iac_path: iacPath,
      scope_id: scopeId,
    };
  }

  function handleSubmit() {
    if (!repoUri || !terraformProvider || !query) return;

    if (schedule) {
      const update: UpdateScheduleRequest = {};
      if (name !== schedule.name) update.name = name;
      if (cron !== schedule.cron) update.cron = cron;
      if (enabled !== schedule.enabled) update.enabled = enabled;
      const newParams = buildParams();
      if (JSON.stringify(newParams) !== JSON.stringify(schedule.params))
        update.params = newParams;
      onSubmit(update);
    } else {
      onSubmit({
        name,
        kind,
        cron,
        enabled,
        params: buildParams(),
        user_id: userEmail,
      });
    }
  }

  return (
    <div className={styles.formWrapper}>
      <TextField
        label="Name"
        value={name}
        onChange={(e) => setName(e.target.value)}
        size="small"
        fullWidth
        required
      />

      <FormControl size="small" fullWidth>
        <InputLabel>Kind</InputLabel>
        <Select
          value={kind}
          label="Kind"
          onChange={(e) => setKind(e.target.value as ScheduleKind)}
        >
          <MenuItem value="DRIFT">Drift</MenuItem>
        </Select>
      </FormControl>

      <TextField
        label="Cron Expression"
        value={cron}
        onChange={(e) => setCron(e.target.value)}
        size="small"
        fullWidth
        required
        placeholder="0 */6 * * *"
      />

      <FormControlLabel
        control={
          <Switch
            checked={enabled}
            onChange={(e) => setEnabled(e.target.checked)}
          />
        }
        label="Enabled"
      />

      <TextField
        label="Repository URI"
        value={repoUri}
        onChange={(e) => setRepoUri(e.target.value)}
        size="small"
        fullWidth
        required
        placeholder="https://github.com/org/repo"
      />

      <FormControl size="small" fullWidth required>
        <InputLabel>Terraform Provider</InputLabel>
        <Select
          value={terraformProvider}
          label="Terraform Provider"
          onChange={(e) => setTerraformProvider(e.target.value)}
        >
          <MenuItem value="azure">Azure</MenuItem>
          <MenuItem value="gcp">GCP</MenuItem>
        </Select>
      </FormControl>

      <TextField
        label="Query"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        size="small"
        fullWidth
        required
        placeholder="Detect and fix infrastructure drift"
      />

      <TextField
        label="IaC Path"
        value={iacPath}
        onChange={(e) => setIacPath(e.target.value)}
        size="small"
        fullWidth
        placeholder="."
      />

      <TextField
        label="Scope ID"
        value={scopeId}
        onChange={(e) => setScopeId(e.target.value)}
        size="small"
        fullWidth
      />

      <div className={styles.actions}>
        <Button variant="contained" size="small" onClick={handleSubmit}>
          {schedule ? "Update" : "Create"}
        </Button>
        <Button variant="outlined" size="small" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </div>
  );
}
