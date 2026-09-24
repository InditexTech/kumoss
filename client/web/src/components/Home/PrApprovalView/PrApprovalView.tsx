// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { useState, useCallback } from "react";
import Typography from "@mui/material/Typography";
import { useSession } from "@/contexts/SessionContext";
import { useNotification } from "@/contexts/NotificationContext";
import { mergePullRequest } from "@/services/core/iac_code";
import { getApiErrorMessage } from "@/services/api";
import { isAllowedUrl } from "@/utils/sanitize";
import { isMergeOnlySession } from "@/utils/session";
import { STRINGS } from "@/constants/strings";
import BlockedReasons from "./BlockedReasons";
import type { PrApprovalStep } from "@/types/ui";
import styles from "./PrApprovalView.module.css";

interface PrApprovalViewProps {
  step: PrApprovalStep;
  onStepChange: (step: PrApprovalStep) => void;
  onApprove: () => void;
  onBackToReport: () => void;
  onContactTeam?: () => void;
}

export default function PrApprovalView({
  step,
  onStepChange,
  onApprove,
  onBackToReport,
  onContactTeam,
}: PrApprovalViewProps) {
  const { session, prDetails } = useSession();
  const { showNotification } = useNotification();
  const [approving, setApproving] = useState(false);

  const confirming = step === "confirming";

  // Drift and import end at the merge, so only the wording differs — the
  // merge itself below is identical for every flow.
  const labels = isMergeOnlySession(session)
    ? {
        prompt: STRINGS.pr.mergePrompt,
        approve: STRINGS.pr.approveAndMerge,
        confirm: STRINGS.pr.confirmMerge,
        inFlight: STRINGS.pr.merging,
      }
    : {
        prompt: STRINGS.pr.applyPrompt,
        approve: STRINGS.assistant.approvePrAndApply,
        confirm: STRINGS.pr.confirmApply,
        inFlight: "Applying…",
      };

  const handleConfirmApply = useCallback(async () => {
    if (!prDetails.number || !session.uuid || approving) return;
    setApproving(true);
    try {
      await mergePullRequest({ session_id: session.uuid });
      onApprove();
    } catch (err) {
      showNotification(
        "failure",
        `Failed to approve pull request: ${getApiErrorMessage(err)}`,
      );
      setApproving(false);
      onStepChange("initial");
    }
  }, [
    prDetails.number,
    session.uuid,
    approving,
    onApprove,
    showNotification,
    onStepChange,
  ]);

  if (session.is_blocked) {
    const compliance = session.compliance_report;
    const banner = session.terraform_report?.potential_impact?.banner;
    const impactDetail =
      banner?.level === "high" ? banner.description || banner.title : undefined;
    return (
      <div className={styles.blockedContainer}>
        <Typography variant="h1" className={styles.heading}>
          {STRINGS.pr.blockedTitle}
        </Typography>
        <Typography variant="bodyText" className={styles.blockedText}>
          {STRINGS.pr.blockedMessage}
        </Typography>

        <BlockedReasons
          impactDetail={impactDetail}
          compliance={compliance?.passed === false ? compliance : undefined}
        />

        <div className={styles.buttonRow}>
          <button
            className={styles.outlineBtn}
            type="button"
            onClick={onBackToReport}
          >
            {STRINGS.assistant.backToReport}
          </button>
          <button
            className={styles.filledBtn}
            type="button"
            onClick={onContactTeam}
          >
            {STRINGS.assistant.contactTeam}
          </button>
        </div>
      </div>
    );
  }

  const showViewPr = prDetails.url && isAllowedUrl(prDetails.url);

  if (confirming) {
    return (
      <div className={styles.container}>
        <Typography variant="h1" className={styles.heading}>{STRINGS.common.confirmTitle}</Typography>
        <Typography variant="h4" className={styles.subtitle}>{STRINGS.common.confirmMessage}</Typography>

        <div className={styles.buttonRow}>
          <button
            className={styles.outlineBtn}
            type="button"
            onClick={onContactTeam}
            disabled={approving}
          >
            {STRINGS.pr.requestReview}
          </button>
          <button
            className={styles.filledBtn}
            type="button"
            onClick={handleConfirmApply}
            disabled={approving || !prDetails.number}
          >
            {approving ? labels.inFlight : labels.confirm}
          </button>
        </div>

        <button
          className={styles.backLink}
          type="button"
          onClick={onBackToReport}
        >
          {STRINGS.assistant.backToReport}
        </button>
      </div>
    );
  }

  return (
    <div className={styles.container}>
      <Typography variant="h1" className={styles.heading}>{STRINGS.pr.ready}</Typography>
      <Typography variant="h4" className={styles.subtitle}>{labels.prompt}</Typography>

      <div className={styles.buttonRow}>
        {showViewPr && (
          <a
            className={styles.noAnchor}
            href={prDetails.url}
            target="_blank"
            rel="noopener noreferrer"
          >
            <button className={styles.outlineBtn} type="button">
              {STRINGS.assistant.viewPr}
            </button>
          </a>
        )}
        <button
          className={styles.filledBtn}
          type="button"
          onClick={() => onStepChange("confirming")}
          disabled={approving || !prDetails.number}
        >
          {labels.approve}
        </button>
      </div>

      <button
        className={styles.backLink}
        type="button"
        onClick={onBackToReport}
      >
        {STRINGS.assistant.backToReport}
      </button>
    </div>
  );
}
