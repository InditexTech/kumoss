// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import Typography from "@mui/material/Typography";
import { StatusBadge } from "@/components/ui";
import type { ComplianceReport, ComplianceViolation } from "@/types";
import styles from "./ComplianceReport.module.css";

const SEVERITY_ORDER: Record<string, number> = {
  critical: 0,
  error: 1,
  warning: 2,
  info: 3,
};

export function sortedViolations(
  violations: ComplianceViolation[],
): ComplianceViolation[] {
  return [...violations].sort(
    (a, b) =>
      (SEVERITY_ORDER[a.severity] ?? 99) - (SEVERITY_ORDER[b.severity] ?? 99),
  );
}

export function ComplianceSummaryCard({ report }: { report: ComplianceReport }) {
  const violations = report.violations ?? [];
  const rules = report.checked_rules ?? [];

  return (
    <div className={styles.summaryCard}>
      <Typography variant="h4" className={styles.summaryLabel}>
        Compliance Check
        <StatusBadge
          variant={report.passed ? "completed" : "failed"}
          label={report.passed ? "PASSED" : "FAILED"}
          className={styles.summaryBadge}
        />
      </Typography>
      {report.summary && (
        <Typography variant="bodyText" className={styles.summaryText}>
          {report.summary}
        </Typography>
      )}
      <Typography variant="subtitle2" className={styles.summaryCounts}>
        {violations.length} violation{violations.length === 1 ? "" : "s"}
        {rules.length > 0 && ` · ${rules.length} rule${rules.length === 1 ? "" : "s"} checked`}
      </Typography>
    </div>
  );
}

export function ComplianceViolations({
  violations = [],
}: {
  violations?: ComplianceViolation[];
}) {
  if (violations.length === 0) return null;

  return (
    <>
      <div className={styles.listHeader}>
        <Typography
          variant="subtitleSemiBold"
          component="h3"
          className={styles.listTitle}
        >
          Violations
          <Typography
            variant="micro"
            component="span"
            sx={{ fontWeight: 500 }}
            className={styles.listCount}
          >
            {violations.length}
          </Typography>
        </Typography>
      </div>

      <div className={styles.list}>
        {sortedViolations(violations).map((violation, i) => (
          <div key={`${violation.rule_id}-${i}`} className={styles.entry}>
            <div className={styles.entryHeader}>
              <Typography
                variant="overline"
                component="span"
                className={`${styles.severity} ${styles[violation.severity] ?? ""}`}
              >
                {violation.severity}
              </Typography>
              <Typography variant="subtitleSemiBold" className={styles.ruleId}>
                {violation.rule_id}
              </Typography>
              {violation.resource && (
                <Typography variant="subtitle2" className={styles.resource}>
                  {violation.resource}
                </Typography>
              )}
            </div>
            <Typography variant="bodyText" className={styles.message}>
              {violation.message}
            </Typography>
            {violation.suggested_fix && (
              <Typography variant="body2" className={styles.suggestedFix}>
                Suggested fix: {violation.suggested_fix}
              </Typography>
            )}
          </div>
        ))}
      </div>
    </>
  );
}
