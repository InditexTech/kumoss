// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { useState } from "react";
import Typography from "@mui/material/Typography";
import { useSession } from "@/contexts/SessionContext";
import type { ApplyResourceChange } from "@/types";
import {
  ApplyChangesList,
  ApplyResourceDetail,
  ApplyRecommendations,
  type ApplyFilterId,
} from "../ResultPanel/ApplyReport/ApplyReport";
import styles from "./ApplyResultView.module.css";

const STATUS_LABELS: Record<string, string> = {
  success: "Succeeded",
  partial: "Partially Applied",
  failed: "Failed",
};

const STATUS_CLASSES: Record<string, string> = {
  success: styles.tabSuccess,
  partial: styles.tabPartial,
  failed: styles.tabFailed,
};

export default function ApplyResultView() {
  const { session } = useSession();
  const results = session.applyResults;
  const report = results?.applyReport;
  const [activeFilter, setActiveFilter] = useState<ApplyFilterId>("all");
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
  const statusLabel = STATUS_LABELS[statusKey] ?? status;
  const statusClass = STATUS_CLASSES[statusKey] ?? "";
  const executionSummary = report?.execution_summary;
  const changes = report?.resource_changes ?? [];
  const recommendations = report?.recommendations ?? [];

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
          <ApplyChangesList
            changes={changes}
            activeFilter={activeFilter}
            setActiveFilter={setActiveFilter}
            onSelect={setSelectedChange}
          />
        )}

        <ApplyRecommendations recommendations={recommendations} />

        {selectedChange && (
          <ApplyResourceDetail
            change={selectedChange}
            onClose={() => setSelectedChange(null)}
          />
        )}
      </div>
    </div>
  );
}
