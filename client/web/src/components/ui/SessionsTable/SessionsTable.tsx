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
  ListSubheader,
  Button,
} from "@mui/material";
import type { SelectChangeEvent } from "@mui/material";
import SearchIcon from "@mui/icons-material/Search";
import CloseIcon from "@mui/icons-material/Close";
import NavigateBeforeIcon from "@mui/icons-material/NavigateBefore";
import NavigateNextIcon from "@mui/icons-material/NavigateNext";
import type { PaginatedResponse } from "@/types/api";
import { getApiErrorMessage } from "@/services/api";
import { getLocalItem, setLocalItem } from "@/services";
import { STORAGE_KEYS } from "@/constants";
import { useNotification } from "@/contexts/NotificationContext";
import styles from "./SessionsTable.module.css";

const PAGE_SIZE_OPTIONS = [10, 15, 25, 50];

/** Typing pause after which a search runs on its own. */
const SEARCH_DEBOUNCE_MS = 400;

/** Last page size the user picked, if it's still a valid option. */
function readStoredPageSize(): number {
  const stored = Number(getLocalItem(STORAGE_KEYS.SESSIONS_PAGE_SIZE));
  return PAGE_SIZE_OPTIONS.includes(stored) ? stored : 0;
}

export interface FilterOption {
  value: string;
  label: string;
  /** Options sharing a group are listed under that heading, in order. */
  group?: string;
}

export interface FilterConfig {
  key: string;
  placeholder: string;
  options: FilterOption[];
}

export interface SearchScopeOption {
  value: string;
  /** Shown in the scope selector. */
  label: string;
  /** The search box placeholder while this scope is picked. */
  placeholder: string;
}

export interface SearchFieldConfig {
  key: string;
  placeholder: string;
  /** Accessible name of the text box. */
  label?: string;
  /**
   * Narrows what the search matches. `key` is the query param it is sent
   * as; the first option is the default and is left out of the URL.
   */
  scope?: { key: string; label: string; options: SearchScopeOption[] };
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
  /** Shown instead of `emptyText` while a search or filter is applied. */
  filteredEmptyText?: string;
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
    filteredEmptyText = "No sessions match your search and filters",
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

  const scopeFingerprint = searchFields
    .map((sf) => (sf.scope ? searchParams.get(sf.scope.key) || "" : ""))
    .join("\0");

  /** The picked scope of each scoped search, by its query param. */
  const appliedScopes = useMemo(() => {
    const result: Record<string, string> = {};
    for (const sf of searchFields) {
      if (!sf.scope) continue;
      const value = searchParams.get(sf.scope.key);
      const known = sf.scope.options.some((o) => o.value === value);
      result[sf.scope.key] = known && value ? value : sf.scope.options[0].value;
    }
    return result;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scopeFingerprint]);

  const [localSearches, setLocalSearches] = useState<Record<string, string>>(appliedSearches);

  // Follow searches changed from outside (back navigation, clear all), but
  // leave the text being typed alone, trailing space included.
  useEffect(() => {
    setLocalSearches((prev) => {
      const next = { ...prev };
      for (const [key, value] of Object.entries(appliedSearches)) {
        if ((prev[key] || "").trim() !== value) next[key] = value;
      }
      return next;
    });
  }, [appliedSearches]);

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

  const flushSearches = useCallback(
    (extra: Record<string, string> = {}) => {
      const updates: Record<string, string> = { page: "", ...extra };
      let searchesChanged = false;
      for (const sf of searchFields) {
        const flushed = (localSearches[sf.key] || "").trim();
        updates[sf.key] = flushed;
        if (flushed !== (appliedSearches[sf.key] || "")) {
          searchesChanged = true;
        }
      }
      if (searchesChanged) {
        updates.page = "";
      }
      updateParams(updates);
    },
    [localSearches, appliedSearches, searchFields, updateParams],
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
        if (!val) continue;
        params[sf.key] = val;
        if (sf.scope && appliedScopes[sf.scope.key] !== sf.scope.options[0].value) {
          params[sf.scope.key] = appliedScopes[sf.scope.key];
        }
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
  }, [page, pageSize, appliedSearches, appliedScopes, filterValues, fetchData, filters, searchFields, showNotification]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  // Run a search once typing pauses; Enter runs it right away.
  const pendingSearch = searchFields.some(
    (sf) => (localSearches[sf.key] || "").trim() !== (appliedSearches[sf.key] || ""),
  );
  useEffect(() => {
    if (!pendingSearch) return;
    const timer = setTimeout(() => flushSearches(), SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [pendingSearch, localSearches, flushSearches]);

  const clearSearch = (key: string) => {
    setLocalSearches((prev) => ({ ...prev, [key]: "" }));
    flushSearches({ [key]: "" });
  };

  const isFiltered =
    searchFields.some((sf) => appliedSearches[sf.key] || localSearches[sf.key]) ||
    filters.some((f) => filterValues[f.key]);

  const clearAll = () => {
    const updates: Record<string, string> = { page: "" };
    for (const sf of searchFields) updates[sf.key] = "";
    for (const f of filters) updates[f.key] = "";
    setLocalSearches({});
    updateParams(updates);
  };

  const startItem = (page - 1) * pageSize + 1;

  return (
    <div className={styles.container}>
      <div className={styles.filters} role="search">
        {searchFields.map((sf) => {
          const scope = sf.scope;
          const scopeValue = scope ? appliedScopes[scope.key] : "";
          const scopeOption = scope?.options.find((o) => o.value === scopeValue);
          const value = localSearches[sf.key] || "";
          return (
            <div key={sf.key} className={styles.searchGroup}>
              {scope && (
                <FormControl variant="standard" size="small">
                  <Select
                    name={scope.key}
                    value={scopeValue}
                    onChange={(e: SelectChangeEvent) =>
                      flushSearches({
                        [scope.key]:
                          e.target.value === scope.options[0].value ? "" : e.target.value,
                      })
                    }
                    inputProps={{ "aria-label": scope.label }}
                    disableUnderline
                    className={styles.scopeSelect}
                  >
                    {scope.options.map((opt) => (
                      <MenuItem key={opt.value} value={opt.value}>
                        {opt.label}
                      </MenuItem>
                    ))}
                  </Select>
                </FormControl>
              )}
              <TextField
                variant="standard"
                placeholder={scopeOption?.placeholder ?? sf.placeholder}
                value={value}
                onChange={(e) =>
                  setLocalSearches((prev) => ({ ...prev, [sf.key]: e.target.value }))
                }
                onKeyDown={(e) => e.key === "Enter" && flushSearches()}
                slotProps={{
                  htmlInput: { "aria-label": sf.label ?? sf.placeholder },
                  input: {
                    startAdornment: (
                      <InputAdornment position="start">
                        <SearchIcon sx={{ fontSize: 20, color: "var(--tbl-ink-soft)" }} />
                      </InputAdornment>
                    ),
                    endAdornment: value ? (
                      <InputAdornment position="end">
                        <IconButton
                          size="small"
                          aria-label={`Clear ${(sf.label ?? "search").toLowerCase()}`}
                          onClick={() => clearSearch(sf.key)}
                        >
                          <CloseIcon sx={{ fontSize: 16 }} />
                        </IconButton>
                      </InputAdornment>
                    ) : null,
                  },
                }}
                className={scope ? styles.searchWide : styles.search}
              />
            </div>
          );
        })}

        {filters.map((f) => {
          const active = filterValues[f.key];
          const items: React.ReactNode[] = [
            <MenuItem key="" value="">
              Any {f.placeholder.toLowerCase()}
            </MenuItem>,
          ];
          let group: string | undefined;
          for (const opt of f.options) {
            if (opt.group && opt.group !== group) {
              group = opt.group;
              items.push(
                <ListSubheader key={`group-${group}`} className={styles.filterGroup}>
                  {group}
                </ListSubheader>,
              );
            }
            items.push(
              <MenuItem key={opt.value} value={opt.value}>
                {opt.label}
              </MenuItem>,
            );
          }
          return (
            <FormControl key={f.key} variant="standard" size="small">
              <Select
                name={f.key}
                value={active}
                onChange={(e: SelectChangeEvent) =>
                  flushSearches({ [f.key]: e.target.value })
                }
                displayEmpty
                renderValue={(v) => {
                  const label = f.options.find((o) => o.value === v)?.label;
                  return label ? `${f.placeholder}: ${label}` : f.placeholder;
                }}
                inputProps={{ "aria-label": f.placeholder }}
                className={`${styles.filterSelect} ${active ? styles.filterActive : ""}`}
                disableUnderline
              >
                {items}
              </Select>
            </FormControl>
          );
        })}

        {isFiltered && (
          <Button size="small" onClick={clearAll} className={styles.clearAll}>
            Clear all
          </Button>
        )}

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
                flushSearches({ pageSize: e.target.value });
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
            {total === 0 ? "0" : `${startItem} - ${total}`}
          </Typography>
          <IconButton
            size="small"
            onClick={() =>
              flushSearches({ page: String(Math.max(1, page - 1)) })
            }
            disabled={page === 1}
          >
            <NavigateBeforeIcon fontSize="small" />
          </IconButton>
          <IconButton
            size="small"
            onClick={() =>
              flushSearches({ page: String(Math.min(totalPages, page + 1)) })
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
                  {isFiltered ? (
                    <>
                      {filteredEmptyText}
                      <Button size="small" onClick={clearAll} className={styles.clearAll}>
                        Clear all
                      </Button>
                    </>
                  ) : (
                    emptyText
                  )}
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
