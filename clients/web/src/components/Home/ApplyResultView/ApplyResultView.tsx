import { useState, useMemo } from "react";
import Typography from "@mui/material/Typography";
import { useSession } from "@/contexts/SessionContext";
import { StatusBadge, PageOverlay } from "@/components/ui";
import type { ApplyResourceChange } from "@/types";
import styles from "./ApplyResultView.module.css";

type FilterId = "all" | "created" | "updated" | "destroyed" | "failed";

const FILTERS: { id: FilterId; label: string }[] = [
  { id: "all", label: "All" },
  { id: "created", label: "Created" },
  { id: "updated", label: "Updated" },
  { id: "destroyed", label: "Destroyed" },
  { id: "failed", label: "Failed" },
];

export default function ApplyResultView() {
  const { session } = useSession();
  const results = session.applyResults;
  const report = results?.applyReport;
  const [activeFilter, setActiveFilter] = useState<FilterId>("all");
  const [selectedChange, setSelectedChange] =
    useState<ApplyResourceChange | null>(null);

  if (!results) {
    return (
      <div className={styles.panel}>
        <p className={styles.emptyState}>No apply results available.</p>
      </div>
    );
  }

  const status = report?.status ?? results.status ?? "Unknown";
  const statusKey = status.toLowerCase();
  const executionSummary = report?.execution_summary as string | undefined;
  const changes = (report?.resource_changes ?? []) as ApplyResourceChange[];
  const recommendations = report?.recommendations as string[] | undefined;
  const statusLabel =
    statusKey === "success"
      ? "Succeeded"
      : statusKey === "partial"
        ? "Partially Applied"
        : statusKey === "failed"
          ? "Failed"
          : status;

  const statusClass =
    statusKey === "success"
      ? styles.tabSuccess
      : statusKey === "partial"
        ? styles.tabPartial
        : statusKey === "failed"
          ? styles.tabFailed
          : "";

  return (
    <div className={styles.panel}>
      <div className={styles.tabBar}>
        <Typography variant="h1" component="button" className={`${styles.tab} ${styles.tabActive} ${statusClass}`}>
          Execution Summary {statusLabel}
        </Typography>
      </div>

      <div className={styles.tabContent}>
        <p className={styles.executionSummaryText}>
          {executionSummary || status}
        </p>

        {changes.length > 0 && (
          <ResourceTable
            changes={changes}
            activeFilter={activeFilter}
            setActiveFilter={setActiveFilter}
            onSelectChange={setSelectedChange}
          />
        )}

        {recommendations && recommendations.length > 0 && (
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
        )}

        {selectedChange && (
          <PageOverlay
            title={selectedChange.resource_name}
            onClose={() => setSelectedChange(null)}
          >
            <ResourceDetailContent change={selectedChange} />
          </PageOverlay>
        )}
      </div>
    </div>
  );
}

// ─── Sub-components ─────────────────────────────────────────

function ResourceDetailContent({ change }: { change: ApplyResourceChange }) {
  return (
    <>
      <div className={styles.detailRow}>
        <Typography variant="label" component="span" className={styles.detailLabel}>Status</Typography>
        <StatusBadge
          variant={change.status === "failed" ? "failed" : change.action}
        />
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
    </>
  );
}

function ResourceTable({
  changes,
  activeFilter,
  setActiveFilter,
  onSelectChange,
}: {
  changes: ApplyResourceChange[];
  activeFilter: FilterId;
  setActiveFilter: (f: FilterId) => void;
  onSelectChange: (change: ApplyResourceChange) => void;
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
                onClick={hasDetails ? () => onSelectChange(change) : undefined}
              >
                <StatusBadge
                  variant={
                    change.status === "failed" ? "failed" : change.action
                  }
                />
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
