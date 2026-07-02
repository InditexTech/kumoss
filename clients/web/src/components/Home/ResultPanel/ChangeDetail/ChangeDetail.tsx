import Typography from "@mui/material/Typography";
import { PageOverlay, StatusBadge } from "@/components/ui";
import { formatResourceName } from "../resultPanelUtils";
import type { TerraformChange } from "@/types";
import styles from "./ChangeDetail.module.css";

interface ChangeDetailProps {
  change: TerraformChange;
  onClose: () => void;
}

function looksLikeCode(text: string): boolean {
  return /^[+\-~#]/m.test(text) || /^\s*resource\s+"/.test(text);
}

export default function ChangeDetail({ change, onClose }: ChangeDetailProps) {
  return (
    <PageOverlay title={formatResourceName(change)} onClose={onClose}>
      <div className={styles.row}>
        <Typography variant="label" component="span" className={styles.label}>Status</Typography>
        <StatusBadge variant={change.action} />
      </div>

      {(change.summary || change.notes) && (
        <div className={styles.row}>
          <Typography variant="label" component="span" className={styles.label}>Description</Typography>
          <Typography variant="bodyText" className={styles.value}>{change.summary || change.notes}</Typography>
        </div>
      )}

      {change.details && (
        <div className={styles.row}>
          <Typography variant="label" component="span" className={styles.label}>Details</Typography>
          {looksLikeCode(change.details) ? (
            <pre className={styles.codeValue}>{change.details}</pre>
          ) : (
            <Typography variant="bodyText" className={styles.value}>{change.details}</Typography>
          )}
        </div>
      )}
    </PageOverlay>
  );
}
