// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { useState, useCallback } from "react";
import Typography from "@mui/material/Typography";
import { useSession } from "@/contexts/SessionContext";
import { useNotification } from "@/contexts/NotificationContext";
import { mergePullRequest } from "@/services/core/iac_code";
import { getApiErrorMessage } from "@/services/api";
import { markPullRequestMerged } from "@/services/pullRequestState";
import { isAllowedUrl } from "@/utils/sanitize";
import { STRINGS } from "@/constants/strings";
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
  const { session, prDetails, updatePrDetails } = useSession();
  const { showNotification } = useNotification();
  const [approving, setApproving] = useState(false);

  const confirming = step === "confirming";
  const highImpactWarning = step === "high_impact_warning";
  const isDriftOperation = session.operation === "drift";
  const prBelongsToSession =
    !prDetails.sessionId || prDetails.sessionId === session.session_id;
  const prId = prBelongsToSession ? prDetails.id : undefined;
  const prUrl = prBelongsToSession ? prDetails.prUrl : undefined;
  const prMerged = prBelongsToSession && prDetails.merged;

  const isHighImpact =
    session.terraform_report?.potential_impact?.banner?.level === "high";

  const handleConfirmApply = useCallback(async () => {
    if (!prId || !session.session_id || approving) return;
    setApproving(true);
    try {
      await mergePullRequest({ session_id: session.session_id });
      if (isDriftOperation) {
        markPullRequestMerged(session.session_id, prId);
        updatePrDetails({ merged: true });
        onBackToReport();
      } else {
        onApprove();
      }
    } catch (err) {
      showNotification(
        "failure",
        `Failed to approve pull request: ${getApiErrorMessage(err)}`,
      );
      setApproving(false);
      onStepChange("initial");
    }
  }, [
    prId,
    session.session_id,
    isDriftOperation,
    approving,
    onApprove,
    onBackToReport,
    updatePrDetails,
    showNotification,
    onStepChange,
  ]);

  if (session.apply_allowed === false) {
    return (
      <div className={styles.blockedContainer}>
        <Typography variant="h1" className={styles.heading}>
          {STRINGS.assistant.deletionDetectedTitle}
        </Typography>
        <Typography variant="bodyText" className={styles.blockedText}>
          {STRINGS.assistant.blockedApplyMessage}
        </Typography>

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

  const showViewPr = prUrl && isAllowedUrl(prUrl);

  if (isDriftOperation && prMerged) {
    return (
      <div className={styles.container}>
        <Typography variant="h1" className={styles.heading}>{STRINGS.pr.merged}</Typography>
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

  if (isDriftOperation) {
    return (
      <div className={styles.container}>
        <Typography variant="h1" className={styles.heading}>{STRINGS.pr.ready}</Typography>
        <Typography variant="h4" className={styles.subtitle}>{STRINGS.pr.mergePrompt}</Typography>

        <div className={styles.buttonRow}>
          {showViewPr && (
            <a
              className={styles.noAnchor}
              href={prUrl}
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
            onClick={handleConfirmApply}
            disabled={approving || !prId}
          >
            {approving ? "Merging…" : STRINGS.pr.merge}
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

  if (highImpactWarning) {
    return (
      <div className={styles.container}>
        <Typography variant="h1" className={styles.heading}>{STRINGS.pr.highImpactTitle}</Typography>
        <Typography variant="h4" className={styles.subtitle}>{STRINGS.pr.highImpactMessage}</Typography>

        <div className={styles.warningBanner}>
          <span className={styles.warningIcon}>⚠</span>
          <Typography variant="body2" component="span" className={styles.warningText}>
            {session.terraform_report?.potential_impact?.banner?.description ??
              STRINGS.pr.highImpactMessage}
          </Typography>
        </div>

        <div className={styles.buttonRow}>
          <button
            className={styles.outlineBtn}
            type="button"
            onClick={() => onStepChange("confirming")}
            disabled={approving}
          >
            {STRINGS.pr.highImpactCancel}
          </button>
          <button
            className={styles.dangerBtn}
            type="button"
            onClick={handleConfirmApply}
            disabled={approving || !prId}
          >
            {approving ? "Applying…" : STRINGS.pr.highImpactConfirm}
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
            onClick={
              isHighImpact
                ? () => onStepChange("high_impact_warning")
                : handleConfirmApply
            }
            disabled={approving || !prId}
          >
            {approving ? "Applying…" : STRINGS.pr.confirmApply}
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
      <Typography variant="h4" className={styles.subtitle}>{STRINGS.pr.applyPrompt}</Typography>

      <div className={styles.buttonRow}>
        {showViewPr && (
          <a
            className={styles.noAnchor}
            href={prUrl}
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
          disabled={approving || !prId}
        >
          {STRINGS.assistant.approvePrAndApply}
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
