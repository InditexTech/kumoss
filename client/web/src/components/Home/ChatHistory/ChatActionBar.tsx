// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { useState, useCallback } from "react";
import { useSearchParams } from "react-router-dom";
import { useSession } from "@/contexts/SessionContext";
import { useNotification } from "@/contexts/NotificationContext";
import { createPullRequest } from "@/services/core/iac_code";
import { getApiErrorMessage } from "@/services/api";
import { STRINGS } from "@/constants/strings";
import styles from "./ChatActionBar.module.css";

interface ChatActionBarProps {
  onResetToReport: () => void;
  disabled?: boolean;
  isApplyResult?: boolean;
}

export default function ChatActionBar({
  onResetToReport,
  disabled,
  isApplyResult,
}: ChatActionBarProps) {
  const { session, prDetails, updatePrDetails } = useSession();
  const { showNotification } = useNotification();
  const [, setSearchParams] = useSearchParams();
  const [loading, setLoading] = useState(false);

  const prCreated = !!prDetails.id;

  const openPrView = useCallback(
    (step: string) => {
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev);
        next.set("view", `pr-${step}`);
        return next;
      }, { replace: true });
    },
    [setSearchParams],
  );

  const handleCreatePr = useCallback(async () => {
    if (!session.session_id || prCreated || loading) return;
    setLoading(true);
    try {
      const res = await createPullRequest({
        session_id: session.session_id,
      });
      updatePrDetails({ id: res.id, prUrl: res.url });
      openPrView("initial");
    } catch (err) {
      showNotification(
        "failure",
        `Failed to create pull request: ${getApiErrorMessage(err)}`,
      );
      setLoading(false);
    }
  }, [
    session.session_id,
    prCreated,
    loading,
    updatePrDetails,
    openPrView,
    showNotification,
  ]);

  const handleContinuePr = useCallback(() => {
    openPrView(prDetails.lastPrStep ?? "initial");
  }, [openPrView, prDetails.lastPrStep]);

  const handleBackToReport = useCallback(() => {
    onResetToReport();
  }, [onResetToReport]);

  const canCreatePr = !!session.session_id && !prCreated && !disabled;

  if (isApplyResult) return null;

  return (
    <div className={styles.bar}>
      <button
        className={styles.actionBtn}
        onClick={handleBackToReport}
        disabled={disabled}
      >
        View Report
      </button>
      {canCreatePr && (
        <button
          className={`${styles.actionBtn} ${styles.actionBtnPrimary}`}
          onClick={handleCreatePr}
          disabled={loading}
        >
          {loading ? "Creating..." : "Create PR"}
        </button>
      )}
      {prCreated && (
        <button
          className={`${styles.actionBtn} ${styles.actionBtnPrimary}`}
          onClick={handleContinuePr}
        >
          {STRINGS.pr.continuePr}
        </button>
      )}
    </div>
  );
}
