// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { useState } from "react";
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

const SUMMARY_CLAMP_CHARS = 300;

export function sortedViolations(
  violations: ComplianceViolation[],
): ComplianceViolation[] {
  return [...violations].sort(
    (a, b) =>
      (SEVERITY_ORDER[a.severity] ?? 99) - (SEVERITY_ORDER[b.severity] ?? 99),
  );
}

function plural(count: number, noun: string) {
  return `${count} ${noun}${count === 1 ? "" : "s"}`;
}

function ComplianceSummaryText({ text }: { text: string }) {
  const [expanded, setExpanded] = useState(false);
  const long = text.length > SUMMARY_CLAMP_CHARS;

  return (
    <div className={styles.summaryBody}>
      <Typography
        variant="bodyText"
        className={`${styles.summaryText} ${long && !expanded ? styles.clamped : ""}`}
      >
        {text}
      </Typography>
      {long && (
        <button
          type="button"
          className={styles.textToggle}
          aria-expanded={expanded}
          onClick={() => setExpanded((open) => !open)}
        >
          {expanded ? "Show less" : "Show more"}
        </button>
      )}
    </div>
  );
}

export function ComplianceSummaryCard({ report }: { report: ComplianceReport }) {
  const violations = report.violations ?? [];
  const rules = report.checked_rules ?? [];

  return (
    <div className={styles.summaryCard}>
      <div className={styles.verdict}>
        <StatusBadge
          variant={report.passed ? "completed" : "failed"}
          label={report.passed ? "PASSED" : "FAILED"}
        />
        <Typography variant="subtitle2" component="span" className={styles.summaryCounts}>
          {plural(violations.length, "violation")}
          {rules.length > 0 && ` · ${plural(rules.length, "rule")} checked`}
        </Typography>
      </div>
      {report.summary && <ComplianceSummaryText text={report.summary} />}
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
    <section className={styles.section}>
      <Typography variant="subtitleSemiBold" component="h3" className={styles.sectionTitle}>
        Violations
        <Typography
          variant="micro"
          component="span"
          sx={{ fontWeight: 500 }}
          className={styles.sectionCount}
        >
          {violations.length}
        </Typography>
      </Typography>

      <ul className={styles.list}>
        {sortedViolations(violations).map((violation, i) => (
          <li
            key={`${violation.rule_id}-${i}`}
            className={`${styles.entry} ${styles[violation.severity] ?? ""}`}
          >
            <div className={styles.entryHeader}>
              <Typography
                variant="overline"
                component="span"
                className={styles.severity}
              >
                {violation.severity}
              </Typography>
              <Typography variant="subtitleSemiBold" component="span" className={styles.ruleId}>
                {violation.rule_id}
              </Typography>
            </div>
            {violation.resource && (
              <Typography variant="subtitle2" className={styles.resource}>
                {violation.resource}
              </Typography>
            )}
            <Typography variant="bodyText" className={styles.message}>
              {violation.message}
            </Typography>
            {violation.suggested_fix && (
              <Typography variant="body2" className={styles.suggestedFix}>
                Suggested fix: {violation.suggested_fix}
              </Typography>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

export function ComplianceRules({
  rules = [],
  violations = [],
}: {
  rules?: string[];
  violations?: ComplianceViolation[];
}) {
  if (rules.length === 0) return null;

  const worst = new Map<string, string>();
  for (const v of sortedViolations(violations)) {
    if (!worst.has(v.rule_id)) worst.set(v.rule_id, v.severity);
  }
  const ordered = [...rules].sort(
    (a, b) =>
      (SEVERITY_ORDER[worst.get(a) ?? ""] ?? 99) -
      (SEVERITY_ORDER[worst.get(b) ?? ""] ?? 99),
  );

  return (
    <section className={styles.section}>
      <Typography variant="subtitleSemiBold" component="h3" className={styles.sectionTitle}>
        Rules checked
        <Typography
          variant="micro"
          component="span"
          sx={{ fontWeight: 500 }}
          className={styles.sectionCount}
        >
          {rules.length}
        </Typography>
      </Typography>

      <ul className={styles.rules}>
        {ordered.map((rule) => {
          const severity = worst.get(rule);
          return (
            <li
              key={rule}
              className={`${styles.rule} ${severity ? (styles[severity] ?? "") : styles.passedRule}`}
              title={severity ? `Violated (${severity})` : "Passed"}
            >
              <span aria-hidden="true" className={styles.ruleIcon}>
                {severity ? "✕" : "✓"}
              </span>
              <Typography variant="subtitle2" component="span">
                {rule}
              </Typography>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
