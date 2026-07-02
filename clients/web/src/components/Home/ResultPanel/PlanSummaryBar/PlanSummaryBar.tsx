import Typography from "@mui/material/Typography";
import { StatusBadge } from "@/components/ui";
import type { PlanSummary } from "@/types";
import styles from "./PlanSummaryBar.module.css";

const ITEMS: { variant: string; label: string; key: keyof PlanSummary }[] = [
  { variant: "create", label: "create", key: "create" },
  { variant: "update", label: "update", key: "update" },
  { variant: "delete", label: "delete", key: "delete" },
  { variant: "recreate", label: "recreate", key: "recreate" },
];

export default function PlanSummaryBar({ summary }: { summary: PlanSummary }) {
  const total =
    summary.create + summary.update + summary.delete + summary.recreate;

  return (
    <div className={styles.summaryBar}>
      <Typography variant="h4" component="span" sx={{ fontWeight: 500 }} className={styles.summaryTotal}>
        {total} resource{total !== 1 ? "s" : ""}
      </Typography>
      <div className={styles.summaryItems}>
        {ITEMS.map(({ variant, label, key }) =>
          summary[key] > 0 ? (
            <StatusBadge
              key={variant}
              variant={variant}
              label={`${summary[key]} ${label}`}
            />
          ) : null,
        )}
      </div>
    </div>
  );
}
