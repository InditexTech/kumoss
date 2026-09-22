// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

// Drift reports have their own shape — a prose `summary`, a `status` and
// `remediated_resources` — so they can't go through the plan report's
// create/update/delete/recreate table.

import Typography from "@mui/material/Typography";
import { PageOverlay } from "@/components/ui";
import type { DriftException, DriftResource, DriftUnreconciled } from "@/types";
import styles from "./DriftReport.module.css";

function SectionHeader({ title, count }: { title: string; count: number }) {
  return (
    <div className={styles.listHeader}>
      <Typography variant="subtitleSemiBold" component="h3" className={styles.listTitle}>
        {title}
        <Typography variant="micro" component="span" sx={{ fontWeight: 500 }} className={styles.listCount}>
          {count}
        </Typography>
      </Typography>
    </div>
  );
}

export function DriftChangesList({
  resources,
  onSelect,
}: {
  resources: DriftResource[];
  onSelect: (resource: DriftResource) => void;
}) {
  return (
    <>
      <SectionHeader title="Remediated Resources" count={resources.length} />

      <div className={styles.list}>
        {resources.map((resource) => (
          <div key={resource.resource_address} className={styles.entry}>
            <div
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

// The drift the round left in place. Unreconciled drift is a shortfall;
// a whitelisted exception is the intended outcome of a rule, so the two
// are never merged into one list.
export function DriftLeftovers({
  unreconciled = [],
  exceptions = [],
}: {
  unreconciled?: DriftUnreconciled[];
  exceptions?: DriftException[];
}) {
  if (unreconciled.length === 0 && exceptions.length === 0) return null;
  return (
    <>
      {unreconciled.length > 0 && (
        <div className={styles.leftoverSection}>
          <SectionHeader title="Drift Not Reconciled" count={unreconciled.length} />
          {unreconciled.map((entry, i) => (
            <div key={i} className={styles.leftoverEntry}>
              {entry.resource_address && (
                <Typography variant="subtitleSemiBold" component="div" className={styles.leftoverAddress}>
                  {entry.resource_address}
                </Typography>
              )}
              <Typography variant="bodyText" component="div" className={styles.detailText}>
                {entry.reason}
              </Typography>
              {entry.details && entry.details.length > 0 && (
                <ul className={styles.detailBullets}>
                  {entry.details.map((detail, j) => (
                    <li key={j}>
                      <Typography variant="body2" className={styles.detailText}>
                        {detail}
                      </Typography>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ))}
        </div>
      )}

      {exceptions.length > 0 && (
        <div className={styles.leftoverSection}>
          <SectionHeader title="Left Alone by Exception Rules" count={exceptions.length} />
          {exceptions.map((entry, i) => (
            <div key={i} className={styles.leftoverEntry}>
              {entry.resource_address && (
                <Typography variant="subtitleSemiBold" component="div" className={styles.leftoverAddress}>
                  {entry.resource_address}
                </Typography>
              )}
              <Typography variant="bodyText" component="div" className={styles.detailText}>
                {entry.change}
              </Typography>
              <Typography variant="body2" component="div" className={styles.leftoverRule}>
                {entry.rule}
              </Typography>
            </div>
          ))}
        </div>
      )}
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
