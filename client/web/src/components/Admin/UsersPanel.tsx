// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { useCallback, useMemo, useState } from "react";
import { MenuItem, Select } from "@mui/material";
import type { SelectChangeEvent } from "@mui/material";
import { useAuth } from "@/contexts/AuthContext";
import { useNotification } from "@/contexts/NotificationContext";
import { getApiErrorMessage } from "@/services/api";
import { listUsers, setUserRoles } from "@/services/core/admin";
import type {
  AdminUserEntry,
  OperationRole,
  PanelRole,
} from "@/types/api";
import { SessionsTable, formatDate } from "@/components/ui";
import type {
  ColumnDef,
  FetchParams,
  FilterConfig,
  SearchFieldConfig,
} from "@/components/ui";
import styles from "./UsersPanel.module.css";

const OPERATION_ROLE_OPTIONS: { value: OperationRole; label: string }[] = [
  { value: "developer", label: "Developer" },
  { value: "devops", label: "DevOps" },
];

const PANEL_ROLE_OPTIONS: { value: PanelRole | ""; label: string }[] = [
  { value: "", label: "No access" },
  { value: "viewer", label: "Viewer" },
  { value: "editor", label: "Editor" },
  { value: "admin", label: "Admin" },
];

const selectSx = {
  fontSize: 13,
  fontWeight: 300,
  minWidth: 120,
} as const;

const filters: FilterConfig[] = [];

const searches: SearchFieldConfig[] = [
  { key: "search", placeholder: "Search by email or name" },
];

export default function UsersPanel() {
  const { user: me } = useAuth();
  const { showNotification } = useNotification();
  const [overrides, setOverrides] = useState<Record<number, AdminUserEntry>>(
    {},
  );
  const [savingId, setSavingId] = useState<number | null>(null);

  const fetchUsers = useCallback(async (params: FetchParams) => {
    const { page, page_size, search } = params;
    const data = await listUsers({
      page: page as number,
      page_size: page_size as number,
      search: search as string | undefined,
    });
    setOverrides((prev) => (Object.keys(prev).length ? {} : prev));
    return data;
  }, []);

  const applyRoles = useCallback(
    async (
      row: AdminUserEntry,
      operationRole: OperationRole,
      panelRole: PanelRole | null,
    ) => {
      setSavingId(row.id);
      try {
        const updated = await setUserRoles(row.id, {
          operation_role: operationRole,
          panel_role: panelRole,
        });
        setOverrides((prev) => ({ ...prev, [row.id]: updated }));
      } catch (err) {
        showNotification(
          "failure",
          `Failed to update roles: ${getApiErrorMessage(err)}`,
        );
      } finally {
        setSavingId(null);
      }
    },
    [showNotification],
  );

  const columns = useMemo<ColumnDef<AdminUserEntry>[]>(
    () => [
      {
        key: "user",
        header: "User",
        width: "34%",
        render: (u) => {
          const row = overrides[u.id] ?? u;
          const title = row.display_name || row.email || `user-${row.id}`;
          return (
            <div>
              <div>{title}</div>
              {row.email && row.display_name && (
                <div className={styles.secondary}>{row.email}</div>
              )}
            </div>
          );
        },
      },
      {
        key: "operation_role",
        header: "Operation role",
        width: "22%",
        render: (u) => {
          const row = overrides[u.id] ?? u;
          return (
            <Select
              variant="standard"
              disableUnderline
              sx={selectSx}
              value={row.operation_role}
              disabled={savingId === row.id}
              onChange={(e: SelectChangeEvent) =>
                void applyRoles(
                  row,
                  e.target.value as OperationRole,
                  row.panel_role,
                )
              }
            >
              {OPERATION_ROLE_OPTIONS.map((opt) => (
                <MenuItem key={opt.value} value={opt.value}>
                  {opt.label}
                </MenuItem>
              ))}
            </Select>
          );
        },
      },
      {
        key: "panel_role",
        header: "Panel role",
        width: "22%",
        render: (u) => {
          const row = overrides[u.id] ?? u;
          // The backend rejects self-demotion with 409; don't offer it.
          const isSelf = me?.id === row.id;
          return (
            <Select
              variant="standard"
              disableUnderline
              displayEmpty
              sx={selectSx}
              value={row.panel_role ?? ""}
              disabled={savingId === row.id || isSelf}
              onChange={(e: SelectChangeEvent) =>
                void applyRoles(
                  row,
                  row.operation_role,
                  (e.target.value || null) as PanelRole | null,
                )
              }
            >
              {PANEL_ROLE_OPTIONS.map((opt) => (
                <MenuItem key={opt.label} value={opt.value}>
                  {opt.label}
                </MenuItem>
              ))}
            </Select>
          );
        },
      },
      {
        key: "created",
        header: "Created",
        width: "22%",
        className: styles.secondary,
        render: (u) => formatDate(u.created_at),
      },
    ],
    [overrides, savingId, me?.id, applyRoles],
  );

  return (
    <div className={styles.wrapper}>
      <SessionsTable<AdminUserEntry>
        columns={columns}
        fetchData={fetchUsers}
        filters={filters}
        rowKey={(u) => String(u.id)}
        searches={searches}
        emptyText="No users found"
      />
    </div>
  );
}
