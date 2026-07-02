import Typography from "@mui/material/Typography";
import styles from "./StatusBadge.module.css";

interface StatusBadgeProps {
  variant: string;
  label?: string;
  className?: string;
}

const VARIANT_CLASS: Record<string, string | undefined> = {
  create: styles.create,
  created: styles.created,
  completed: styles.completed,
  succeeded: styles.succeeded,
  successfully_imported: styles.successfully_imported,
  generated: styles.generated,
  update: styles.update,
  updated: styles.updated,
  partial: styles.partial,
  recreate: styles.recreate,
  recreated: styles.recreated,
  delete: styles.delete,
  deleted: styles.deleted,
  failed: styles.failed,
  not_imported: styles.not_imported,
  destroyed: styles.destroyed,
  started: styles.started,
  generating: styles.generating,
  no_change: styles.no_change,
  untracked: styles.untracked,
};

export default function StatusBadge({ variant, label, className }: StatusBadgeProps) {
  const key = variant?.toLowerCase() ?? "";
  const colorClass = VARIANT_CLASS[key] ?? styles.default;
  const text = label ?? key.replace(/_/g, " ").toUpperCase();

  return (
    <Typography variant="overline" component="span" className={`${styles.badge} ${colorClass}${className ? ` ${className}` : ""}`}>
      {text}
    </Typography>
  );
}
