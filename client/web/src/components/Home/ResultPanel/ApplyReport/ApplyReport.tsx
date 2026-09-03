// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

// Apply reports have their own shape — a `status`, a prose
// `execution_summary`, per-resource `resource_changes` and
// `recommendations` — so they can't go through the plan report's
// create/update/delete/recreate table. Shared by the wizard's
// ApplyResultView and the session detail's artifact viewer.

import { useMemo } from "react";
import Typography from "@mui/material/Typography";
import { StatusBadge, PageOverlay } from "@/components/ui";
import type { ApplyResourceChange } from "@/types";
import styles from "./ApplyReport.module.css";

export type ApplyFilterId = "all" | "created" | "updated" | "destroyed" | "failed";

const FILTERS: { id: ApplyFilterId; label: string }[] = [
  { id: "all", label: "All" },
  { id: "created", label: "Created" },
  { id: "updated", label: "Updated" },
  { id: "destroyed", label: "Destroyed" },
  { id: "failed", label: "Failed" },
];

// A resource that failed badges as failed, whatever action it attempted.
function statusVariant(change: ApplyResourceChange): string {
  return change.status === "failed" ? "failed" : change.action;
}

export function ApplyChangesList({
  changes,
  activeFilter,
  setActiveFilter,
  onSelect,
}: {
  changes: ApplyResourceChange[];
  activeFilter: ApplyFilterId;
  setActiveFilter: (f: ApplyFilterId) => void;
  onSelect: (change: ApplyResourceChange) => void;
}) {
  const counts = useMemo(() => {
    const c: Record<string, number> = {
      created: 0,
      updated: 0,
      destroyed: 0,
      failed: 0,
    };
    changes.forEach((ch) => {
      if (ch.status === "failed") c.failed++;
      if (ch.action in c) c[ch.action]++;
    });
    return c;
  }, [changes]);

  const filtered = useMemo(() => {
    if (activeFilter === "all") return changes;
    if (activeFilter === "failed")
      return changes.filter((ch) => ch.status === "failed");
    return changes.filter((ch) => ch.action === activeFilter);
  }, [changes, activeFilter]);

  return (
    <>
      <div className={styles.filterBar}>
        {FILTERS.map(({ id, label }) => {
          const count = id === "all" ? changes.length : (counts[id] ?? 0);
          return (
            <button
              key={id}
              className={`${styles.filterTab} ${activeFilter === id ? styles.filterTabActive : ""}`}
              onClick={() => setActiveFilter(id)}
            >
              {label}
              <span className={styles.filterCount}>{count}</span>
            </button>
          );
        })}
      </div>

      <div className={styles.changesTable}>
        {filtered.map((change, i) => {
          const hasDetails = !!change.details || !!change.error_message;
          return (
            <div key={i} className={styles.changeEntry}>
              <div
                className={`${styles.changeRow} ${hasDetails ? styles.changeRowClickable : ""}`}
                onClick={hasDetails ? () => onSelect(change) : undefined}
              >
                <StatusBadge variant={statusVariant(change)} />
                <p className={styles.changeName}>{change.resource_name}</p>
                <p className={styles.changeNotes}>{change.resource_type}</p>
              </div>
            </div>
          );
        })}
      </div>
    </>
  );
}

export function ApplyResourceDetail({
  change,
  onClose,
}: {
  change: ApplyResourceChange;
  onClose: () => void;
}) {
  return (
    <PageOverlay title={change.resource_name} onClose={onClose}>
      <div className={styles.detailRow}>
        <Typography variant="label" component="span" className={styles.detailLabel}>Status</Typography>
        <StatusBadge variant={statusVariant(change)} />
      </div>

      <div className={styles.detailRow}>
        <Typography variant="label" component="span" className={styles.detailLabel}>Type</Typography>
        <Typography variant="bodyText" className={styles.detailValue}>{change.resource_type}</Typography>
      </div>

      {change.error_message && (
        <div className={styles.detailRow}>
          <Typography variant="label" component="span" className={styles.detailLabel}>Error</Typography>
          <Typography variant="body2" className={styles.detailError}>{change.error_message}</Typography>
        </div>
      )}

      {change.details && (
        <div className={styles.detailRow}>
          <Typography variant="label" component="span" className={styles.detailLabel}>Details</Typography>
          <pre className={styles.detailCode}>{change.details}</pre>
        </div>
      )}
    </PageOverlay>
  );
}

export function ApplyRecommendations({
  recommendations,
}: {
  recommendations: string[];
}) {
  if (recommendations.length === 0) return null;
  return (
    <div className={styles.recommendationsSection}>
      <Typography variant="h5" component="h3" className={styles.subsectionTitle}>Recommendations</Typography>
      <ul className={styles.recommendationsList}>
        {recommendations.map((rec, i) => (
          <Typography variant="body2" component="li" key={i} className={styles.recommendationItem}>
            {rec}
          </Typography>
        ))}
      </ul>
    </div>
  );
}
