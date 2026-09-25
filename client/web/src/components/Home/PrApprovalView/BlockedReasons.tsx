// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { useState } from "react";
import Typography from "@mui/material/Typography";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import { STRINGS } from "@/constants/strings";
import {
  ComplianceViolations,
  sortedViolations,
} from "../ResultPanel/ComplianceReport/ComplianceReport";
import type { ComplianceReport, ComplianceViolation } from "@/types";
import styles from "./BlockedReasons.module.css";

const BLOCKING_SEVERITIES = new Set(["critical", "error"]);

function plural(count: number, noun: string) {
  return `${count} ${noun}${count === 1 ? "" : "s"}`;
}

function CompactViolation({ violation }: { violation: ComplianceViolation }) {
  return (
    <li className={styles.violation}>
      <Typography
        variant="overline"
        component="span"
        className={`${styles.severity} ${styles[violation.severity] ?? ""}`}
      >
        {violation.severity}
      </Typography>
      <Typography variant="subtitleSemiBold" component="span">
        {violation.rule_id}
      </Typography>
      {violation.resource && (
        <Typography variant="subtitle2" component="span" className={styles.resource}>
          {violation.resource}
        </Typography>
      )}
      <Typography variant="body2" component="span" className={styles.message}>
        {violation.message}
      </Typography>
    </li>
  );
}

interface BlockedReasonsProps {
  impactDetail?: string;
  compliance?: ComplianceReport;
}

export default function BlockedReasons({
  impactDetail,
  compliance,
}: BlockedReasonsProps) {
  const [open, setOpen] = useState(false);
  const [expanded, setExpanded] = useState(false);

  const violations = sortedViolations(compliance?.violations ?? []);
  const blocking = violations.filter((v) => BLOCKING_SEVERITIES.has(v.severity));
  const shown = blocking.length > 0 ? blocking : violations;
  const hasMore =
    violations.length > shown.length || violations.some((v) => v.suggested_fix);

  if (!impactDetail && !compliance) return null;

  const complianceSummary = plural(
    shown.length,
    blocking.length > 0 ? "blocking violation" : "violation",
  );
  const summary = [
    impactDetail && STRINGS.pr.highImpactReason,
    compliance && complianceSummary,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <div className={styles.panel}>
      <button
        type="button"
        className={styles.heading}
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        <ExpandMoreIcon
          fontSize="small"
          className={`${styles.chevron} ${open ? styles.chevronOpen : ""}`}
        />
        <Typography variant="subtitleSemiBold" component="span" className={styles.title}>
          {STRINGS.pr.blockedWhy}
        </Typography>
        <Typography variant="body2" component="span" className={styles.summary}>
          {summary}
        </Typography>
      </button>
      {open && (
        <ul className={styles.reasons}>
          {impactDetail && (
            <li className={styles.reason}>
              <Typography variant="subtitleSemiBold" component="span" className={styles.label}>
                {STRINGS.pr.highImpactReason}
              </Typography>
              <Typography variant="body2" component="span">
                {impactDetail}
              </Typography>
            </li>
          )}
          {compliance && (
            <li className={styles.reason}>
              <Typography variant="subtitleSemiBold" component="span" className={styles.label}>
                {STRINGS.pr.complianceReason}
              </Typography>
              <div className={styles.detail}>
                {expanded ? (
                  <div className={styles.full}>
                    <ComplianceViolations violations={violations} />
                  </div>
                ) : (
                  <ul className={styles.violations}>
                    {shown.map((violation, i) => (
                      <CompactViolation
                        key={`${violation.rule_id}-${i}`}
                        violation={violation}
                      />
                    ))}
                  </ul>
                )}
                {hasMore && (
                  <button
                    type="button"
                    className={styles.toggle}
                    aria-expanded={expanded}
                    onClick={() => setExpanded((open) => !open)}
                  >
                    {expanded
                      ? STRINGS.pr.hideFindings
                      : `${STRINGS.pr.showAllFindings} (${violations.length})`}
                  </button>
                )}
              </div>
            </li>
          )}
        </ul>
      )}
    </div>
  );
}
