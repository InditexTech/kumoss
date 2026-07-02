import { useMemo } from "react";
import Typography from "@mui/material/Typography";
import { StatusBadge } from "@/components/ui";
import { FILTERS, formatResourceName } from "../resultPanelUtils";
import type { FilterId } from "../resultPanelUtils";
import type { TerraformChange } from "@/types";
import styles from "./ChangesTable.module.css";

interface ChangesTableProps {
  changes: TerraformChange[];
  activeFilter: FilterId;
  setActiveFilter: (f: FilterId) => void;
  onSelectChange: (change: TerraformChange) => void;
}

export default function ChangesTable({
  changes,
  activeFilter,
  setActiveFilter,
  onSelectChange,
}: ChangesTableProps) {
  const counts = useMemo(() => {
    const c: Record<string, number> = {
      create: 0,
      update: 0,
      delete: 0,
      recreate: 0,
    };
    changes.forEach((ch) => {
      if (ch.action in c) c[ch.action]++;
    });
    return c;
  }, [changes]);

  const filtered = useMemo(
    () =>
      activeFilter === "all"
        ? changes
        : changes.filter((ch) => ch.action === activeFilter),
    [changes, activeFilter],
  );

  return (
    <>
      <div className={styles.filterBar}>
        {FILTERS.map(({ id, label }) => {
          const count = id === "all" ? changes.length : (counts[id] ?? 0);
          return (
            <Typography
              variant="subtitleSemiBold"
              component="button"
              key={id}
              className={`${styles.filterTab} ${activeFilter === id ? styles.filterTabActive : ""}`}
              onClick={() => setActiveFilter(id)}
            >
              {label}
              <Typography variant="micro" component="span" sx={{ fontWeight: 500 }} className={styles.filterCount}>{count}</Typography>
            </Typography>
          );
        })}
      </div>

      <div className={styles.changesTable}>
        {filtered.map((change, i) => {
          const hasDetails = !!change.details;
          return (
            <div key={i} className={styles.changeEntry}>
              <div
                className={`${styles.changeRow} ${hasDetails ? styles.changeRowClickable : ""}`}
                onClick={hasDetails ? () => onSelectChange(change) : undefined}
              >
                <StatusBadge variant={change.action} />
                <Typography variant="subtitleSemiBold" className={styles.changeName}>
                  {formatResourceName(change)}
                </Typography>
                <Typography variant="subtitle2" className={styles.changeNotes}>
                  {change.notes || change.summary || ""}
                </Typography>
              </div>
            </div>
          );
        })}
      </div>
    </>
  );
}
