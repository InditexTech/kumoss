// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

// Drift reports have their own shape — a prose `summary`, a `status` and
// `remediated_resources` — so they can't go through the plan report's
// create/update/delete/recreate table.

import Typography from "@mui/material/Typography";
import { PageOverlay } from "@/components/ui";
import type { DriftResource } from "@/types";
import styles from "./DriftReport.module.css";

export function DriftChangesList({
  resources,
  onSelect,
}: {
  resources: DriftResource[];
  onSelect: (resource: DriftResource) => void;
}) {
  return (
    <>
      <div className={styles.listHeader}>
        <Typography variant="subtitleSemiBold" component="span" className={styles.listTitle}>
          Remediated Resources
          <Typography variant="micro" component="span" sx={{ fontWeight: 500 }} className={styles.listCount}>
            {resources.length}
          </Typography>
        </Typography>
      </div>

      <div className={styles.list}>
        {resources.map((resource) => (
          <div key={resource.resource_address} className={styles.entry}>
              className={styles.row}
              onClick={() => onSelect(resource)}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => e.key === "Enter" && onSelect(resource)}
            >
              <Typography variant="subtitleSemiBold" className={styles.resourceAddress}>
                {resource.resource_address}
              </Typography>
              <Typography variant="subtitle2" className={styles.filePath}>
                {resource.file_path}
              </Typography>
              <Typography variant="subtitle2" className={styles.description}>
                {resource.changes?.[0]?.change_description ?? ""}
              </Typography>
            </div>
          </div>
        ))}
      </div>
    </>
  );
}

export function DriftResourceDetail({
  resource,
  onClose,
}: {
  resource: DriftResource;
  onClose: () => void;
}) {
  return (
    <PageOverlay title={resource.resource_address} onClose={onClose}>
      <div className={styles.detailRow}>
        <Typography variant="label" component="span" className={styles.detailLabel}>File</Typography>
        <Typography variant="bodyText" className={styles.detailValue}>{resource.file_path}</Typography>
      </div>

      {(resource.changes ?? []).map((change, i) => (
        <div key={i} className={styles.changeSection}>
          <div className={styles.detailRow}>
            <Typography variant="label" component="span" className={styles.detailLabel}>Change</Typography>
            <Typography variant="bodyText" className={styles.detailValue}>
              {change.change_description}
            </Typography>
          </div>

          {change.details && change.details.length > 0 && (
            <div className={styles.detailRow}>
              <Typography variant="label" component="span" className={styles.detailLabel}>Details</Typography>
              <ul className={styles.detailBullets}>
                {change.details.map((detail, j) => (
                  <li key={j}>
                    <Typography variant="bodyText" className={styles.detailText}>{detail}</Typography>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {change.reason && (
            <div className={styles.detailRow}>
              <Typography variant="label" component="span" className={styles.detailLabel}>Reason</Typography>
              <Typography variant="bodyText" className={styles.detailValue}>{change.reason}</Typography>
            </div>
          )}
        </div>
      ))}
    </PageOverlay>
  );
}
