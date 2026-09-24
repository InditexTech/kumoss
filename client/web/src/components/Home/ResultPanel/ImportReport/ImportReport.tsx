// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

// Import reports have their own shape — a `status`, a prose
// `execution_summary`, per-resource `imported_resources`, the
// `excluded_resources` the exception list withheld, a `state_alignment`
// note and `recommendations` — so they can't go through the plan report's
// create/update/delete/recreate table. Shared by the wizard's ResultPanel
// and the session detail's artifact viewer.

import { useMemo } from "react";
import Typography from "@mui/material/Typography";
import { StatusBadge, PageOverlay } from "@/components/ui";
import type { ExcludedResource, ImportedResource } from "@/types";
import styles from "./ImportReport.module.css";

export type ImportFilterId = "all" | "imported" | "failed";

const FILTERS: { id: ImportFilterId; label: string }[] = [
  { id: "all", label: "All" },
  { id: "imported", label: "Imported" },
  { id: "failed", label: "Failed" },
];

export function ImportedResourcesList({
  resources,
  activeFilter,
  setActiveFilter,
  onSelect,
}: {
  resources: ImportedResource[];
  activeFilter: ImportFilterId;
  setActiveFilter: (f: ImportFilterId) => void;
  onSelect: (resource: ImportedResource) => void;
}) {
  const counts = useMemo(() => {
    const c: Record<ImportFilterId, number> = {
      all: resources.length,
      imported: 0,
      failed: 0,
    };
    resources.forEach((r) => {
      if (r.status in c) c[r.status]++;
    });
    return c;
  }, [resources]);

  const filtered = useMemo(
    () =>
      activeFilter === "all"
        ? resources
        : resources.filter((r) => r.status === activeFilter),
    [resources, activeFilter],
  );

  return (
    <>
      <div className={styles.filterBar}>
        {FILTERS.map(({ id, label }) => (
          <button
            key={id}
            className={`${styles.filterTab} ${activeFilter === id ? styles.filterTabActive : ""}`}
            onClick={() => setActiveFilter(id)}
          >
            {label}
            <span className={styles.filterCount}>{counts[id]}</span>
          </button>
        ))}
      </div>

      <div className={styles.list}>
        {filtered.map((resource) => (
          <div key={resource.resource_address} className={styles.entry}>
            <div
              className={styles.row}
              onClick={() => onSelect(resource)}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => e.key === "Enter" && onSelect(resource)}
            >
              <StatusBadge variant={resource.status} />
              <Typography variant="subtitleSemiBold" className={styles.resourceAddress}>
                {resource.resource_address}
              </Typography>
              <Typography variant="subtitle2" className={styles.resourceId}>
                {resource.resource_id}
              </Typography>
            </div>
          </div>
        ))}
      </div>
    </>
  );
}

// Withheld by the import exception list: skipped on purpose, never
// attempted, so they are listed apart from the failures.
export function ImportExclusions({
  excluded = [],
}: {
  excluded?: ExcludedResource[];
}) {
  if (excluded.length === 0) return null;
  return (
    <div className={styles.section}>
      <div className={styles.listHeader}>
        <Typography variant="subtitleSemiBold" component="h3" className={styles.listTitle}>
          Excluded by Import Exceptions
          <Typography variant="micro" component="span" sx={{ fontWeight: 500 }} className={styles.listCount}>
            {excluded.length}
          </Typography>
        </Typography>
      </div>
      {excluded.map((entry) => (
        <div key={entry.resource_id} className={styles.excludedEntry}>
          <Typography variant="subtitleSemiBold" component="div" className={styles.excludedId}>
            {entry.resource_id}
          </Typography>
          <Typography variant="body2" component="div" className={styles.detailText}>
            {entry.details}
          </Typography>
        </div>
      ))}
    </div>
  );
}

export function ImportStateAlignment({ text }: { text?: string }) {
  if (!text) return null;
  return (
    <div className={styles.section}>
      <Typography variant="h5" component="h3" className={styles.subsectionTitle}>
        State Alignment
      </Typography>
      <Typography variant="bodyText" component="div" className={styles.detailText}>
        {text}
      </Typography>
    </div>
  );
}

export function ImportedResourceDetail({
  resource,
  onClose,
}: {
  resource: ImportedResource;
  onClose: () => void;
}) {
  return (
    <PageOverlay title={resource.resource_address} onClose={onClose}>
      <div className={styles.detailRow}>
        <Typography variant="label" component="span" className={styles.detailLabel}>Status</Typography>
        <StatusBadge variant={resource.status} />
      </div>

      <div className={styles.detailRow}>
        <Typography variant="label" component="span" className={styles.detailLabel}>Resource ID</Typography>
        <Typography variant="bodyText" className={`${styles.detailValue} ${styles.detailMono}`}>
          {resource.resource_id}
        </Typography>
      </div>

      {resource.error_message && (
        <div className={styles.detailRow}>
          <Typography variant="label" component="span" className={styles.detailLabel}>Error</Typography>
          <Typography variant="body2" className={styles.detailError}>{resource.error_message}</Typography>
        </div>
      )}

      {resource.details && (
        <div className={styles.detailRow}>
          <Typography variant="label" component="span" className={styles.detailLabel}>Details</Typography>
          <Typography variant="bodyText" className={styles.detailValue}>{resource.details}</Typography>
        </div>
      )}
    </PageOverlay>
  );
}
