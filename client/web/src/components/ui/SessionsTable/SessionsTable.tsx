// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import React, { useState, useEffect, useCallback, useMemo } from "react";
import { useSearchParams } from "react-router-dom";
import {
  TextField,
  InputAdornment,
  Select,
  MenuItem,
  FormControl,
  IconButton,
  Typography,
} from "@mui/material";
import type { SelectChangeEvent } from "@mui/material";
import SearchIcon from "@mui/icons-material/Search";
import NavigateBeforeIcon from "@mui/icons-material/NavigateBefore";
import NavigateNextIcon from "@mui/icons-material/NavigateNext";
import type { PaginatedResponse } from "@/types/api";
import { getApiErrorMessage } from "@/services/api";
import { getLocalItem, setLocalItem } from "@/services";
import { STORAGE_KEYS } from "@/constants";
import { useNotification } from "@/contexts/NotificationContext";
import styles from "./SessionsTable.module.css";

const PAGE_SIZE_OPTIONS = [10, 15, 25, 50];

/** Last page size the user picked, if it's still a valid option. */
function readStoredPageSize(): number {
  const stored = Number(getLocalItem(STORAGE_KEYS.SESSIONS_PAGE_SIZE));
  return PAGE_SIZE_OPTIONS.includes(stored) ? stored : 0;
}

export interface FilterOption {
  value: string;
  label: string;
}

export interface FilterConfig {
  key: string;
  placeholder: string;
  options: FilterOption[];
}

export interface SearchFieldConfig {
  key: string;
  placeholder: string;
}

export interface ColumnDef<T> {
  key: string;
  header: string;
  width?: string;
  className?: string;
  render: (row: T) => React.ReactNode;
}

export interface FetchParams {
  page: number;
  page_size: number;
  [key: string]: string | number | boolean | undefined;
}

interface SessionsTableProps<T> {
  columns: ColumnDef<T>[];
  fetchData: (params: FetchParams) => Promise<PaginatedResponse<T>>;
  filters: FilterConfig[];
  rowKey: (row: T) => string;
  onRowClick?: (row: T) => void;
  searches?: SearchFieldConfig[];
  searchPlaceholder?: string;
  extraToolbarContent?: React.ReactNode;
  pageSize?: number;
  emptyText?: string;
}

export function formatDate(dateStr: string | null): string {
  if (!dateStr) return "-";
  const d = new Date(dateStr);
  const day = String(d.getDate()).padStart(2, "0");
  const month = String(d.getMonth() + 1).padStart(2, "0");
  const year = d.getFullYear();
  const hours = String(d.getHours()).padStart(2, "0");
  const minutes = String(d.getMinutes()).padStart(2, "0");
  return `${day}.${month}.${year}, ${hours}:${minutes}`;
}

export function truncate(text: string | null, max = 60): string {
  if (!text) return "-";
  return text.length > max ? text.substring(0, max) + "..." : text;
}

function SessionsTableInner<T>(props: SessionsTableProps<T>) {
  const {
    columns,
    fetchData,
    filters,
    rowKey,
    onRowClick,
    searches: searchesProp,
    searchPlaceholder = "Search...",
    extraToolbarContent,
    pageSize: defaultPageSize = 15,
    emptyText = "No sessions found",
  } = props;

  const searchFields = useMemo(
    () => searchesProp ?? [{ key: "search", placeholder: searchPlaceholder }],
    [searchesProp, searchPlaceholder],
  );

  const [searchParams, setSearchParams] = useSearchParams();
  const { showNotification } = useNotification();
  const [rows, setRows] = useState<T[]>([]);
  const [total, setTotal] = useState(0);
  const [totalPages, setTotalPages] = useState(0);
  const [loading, setLoading] = useState(true);

  const page = Number(searchParams.get("page")) || 1;
  const pageSize =
    Number(searchParams.get("pageSize")) ||
    readStoredPageSize() ||
    defaultPageSize;

  const searchFingerprint = searchFields
    .map((sf) => searchParams.get(sf.key) || "")
    .join("\0");

  const appliedSearches = useMemo(() => {
    const result: Record<string, string> = {};
    for (const sf of searchFields) {
      result[sf.key] = searchParams.get(sf.key) || "";
    }
    return result;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchFingerprint]);

  const [localSearches, setLocalSearches] = useState<Record<string, string>>(appliedSearches);

  const filterFingerprint = filters
    .map((f) => searchParams.get(f.key) || "")
    .join("\0");

  const filterValues = useMemo(() => {
    const result: Record<string, string> = {};
    for (const f of filters) {
      result[f.key] = searchParams.get(f.key) || "";
    }
    return result;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filterFingerprint]);

  const updateParams = useCallback(
    (updates: Record<string, string>) => {
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev);
        for (const [key, value] of Object.entries(updates)) {
          if (value) next.set(key, value);
          else next.delete(key);
        }
        return next;
      });
    },
    [setSearchParams],
  );

  const applySearch = useCallback(
    (key: string) => {
      updateParams({ page: "", [key]: (localSearches[key] || "").trim() });
    },
    [localSearches, updateParams],
  );

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const params: FetchParams = {
        page,
        page_size: pageSize,
      };
      for (const sf of searchFields) {
        const val = appliedSearches[sf.key];
        if (val) params[sf.key] = val;
      }
      for (const f of filters) {
        const val = filterValues[f.key];
        if (val) params[f.key] = val;
      }
      const data = await fetchData(params);
      setRows(data.items);
      setTotal(data.total);
      setTotalPages(data.total_pages ?? Math.ceil(data.total / pageSize));
    } catch (err) {
      showNotification(
        "failure",
        `Failed to load sessions: ${getApiErrorMessage(err)}`,
      );
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, appliedSearches, filterValues, fetchData, filters, searchFields, showNotification]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const startItem = (page - 1) * pageSize + 1;

  return (
    <div className={styles.container}>
      <div className={styles.filters}>
        {searchFields.map((sf) => (
          <TextField
            key={sf.key}
            variant="standard"
            placeholder={sf.placeholder}
            value={localSearches[sf.key] || ""}
            onChange={(e) =>
              setLocalSearches((prev) => ({ ...prev, [sf.key]: e.target.value }))
            }
            onKeyDown={(e) =>
              e.key === "Enter" && applySearch(sf.key)
            }
            slotProps={{
              input: {
                startAdornment: (
                  <InputAdornment position="start">
                    <SearchIcon sx={{ fontSize: 20, color: "var(--tbl-ink-soft)" }} />
                  </InputAdornment>
                ),
              },
            }}
            sx={{ minWidth: { xs: 140, sm: 200 } }}
          />
        ))}

        {filters.map((f) => (
          <FormControl key={f.key} variant="standard" size="small">
            <Select
              name={f.key}
              value={filterValues[f.key]}
              onChange={(e: SelectChangeEvent) =>
                updateParams({ [f.key]: e.target.value, page: "" })
              }
              displayEmpty
              sx={{
                fontSize: 13,
                fontWeight: 300,
                textTransform: "uppercase",
                "& .MuiInput-underline:before": { border: "none" },
                "& .MuiInput-underline:after": { border: "none" },
              }}
              disableUnderline
            >
              <MenuItem value="">{f.placeholder}</MenuItem>
              {f.options.map((opt) => (
                <MenuItem key={opt.value} value={opt.value}>
                  {opt.label}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
        ))}

        {extraToolbarContent && (
          <div className={styles.extraContent}>{extraToolbarContent}</div>
        )}

        <div className={styles.inlinePagination}>
          <FormControl variant="standard" size="small">
            <Select
              name="page-size"
              value={String(pageSize)}
              onChange={(e: SelectChangeEvent) => {
                setLocalItem(STORAGE_KEYS.SESSIONS_PAGE_SIZE, e.target.value);
                updateParams({ pageSize: e.target.value, page: "" });
              }}
              disableUnderline
              sx={{ fontSize: 14, fontWeight: 300 }}
            >
              {PAGE_SIZE_OPTIONS.map((n) => (
                <MenuItem key={n} value={String(n)}>
                  {n}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
          <Typography
            variant="body2"
            sx={{ mr: 0.5, fontWeight: 300, color: "var(--tbl-ink-soft)" }}
          >
            {startItem} - {total}
          </Typography>
          <IconButton
            size="small"
            onClick={() =>
              updateParams({ page: String(Math.max(1, page - 1)) })
            }
            disabled={page === 1}
          >
            <NavigateBeforeIcon fontSize="small" />
          </IconButton>
          <IconButton
            size="small"
            onClick={() =>
              updateParams({ page: String(Math.min(totalPages, page + 1)) })
            }
            disabled={page >= totalPages}
          >
            <NavigateNextIcon fontSize="small" />
          </IconButton>
        </div>
      </div>

      <div className={styles.tableWrapper}>
        <table className={styles.table}>
          <colgroup>
            {columns.map((col) => (
              <col key={col.key} style={col.width ? { width: col.width } : undefined} />
            ))}
          </colgroup>
          <thead>
            <tr>
              {columns.map((col) => (
                <th key={col.key}>{col.header}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={columns.length} className={styles.emptyRow}>
                  Loading...
                </td>
              </tr>
            ) : rows.length === 0 ? (
              <tr>
                <td colSpan={columns.length} className={styles.emptyRow}>
                  {emptyText}
                </td>
              </tr>
            ) : (
              rows.map((row) => (
                <tr
                  key={rowKey(row)}
                  onClick={onRowClick ? () => onRowClick(row) : undefined}
                  className={onRowClick ? styles.clickableRow : undefined}
                >
                  {columns.map((col) => (
                    <td key={col.key} className={col.className}>
                      {col.render(row)}
                    </td>
                  ))}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function SessionsTable<T>(props: SessionsTableProps<T>) {
  return <SessionsTableInner {...props} />;
}
