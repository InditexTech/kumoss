// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { useState, useCallback } from "react";
import { useSearchParams } from "react-router-dom";
import { useSession } from "@/contexts/SessionContext";
import { useNotification } from "@/contexts/NotificationContext";
import { createPullRequest } from "@/services/core/iac_code";
import { getApiErrorMessage } from "@/services/api";
import { useRefreshSessionLock } from "@/hooks/useSessionLock";
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
  const refreshLock = useRefreshSessionLock();

  const prCreated = !!prDetails.number;

  const openPrView = useCallback(
    async (step: string) => {
      await refreshLock().catch(() => undefined);
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev);
        next.set("view", `pr-${step}`);
        return next;
      }, { replace: true });
    },
    [refreshLock, setSearchParams],
  );

  const handleCreatePr = useCallback(async () => {
    if (!session.uuid || prCreated || loading) return;
    setLoading(true);
    try {
      const res = await createPullRequest({
        session_id: session.uuid,
      });
      updatePrDetails({ number: res.id, url: res.url });
      await openPrView("initial");
    } catch (err) {
      showNotification(
        "failure",
        `Failed to create pull request: ${getApiErrorMessage(err)}`,
      );
      setLoading(false);
    }
  }, [
    session.uuid,
    prCreated,
    loading,
    updatePrDetails,
    openPrView,
    showNotification,
  ]);

  const handleContinuePr = useCallback(async () => {
    if (loading) return;
    setLoading(true);
    await openPrView(prDetails.lastPrStep ?? "initial");
    setLoading(false);
  }, [loading, openPrView, prDetails.lastPrStep]);

  const handleBackToReport = useCallback(() => {
    onResetToReport();
  }, [onResetToReport]);

  const canCreatePr = !!session.uuid && !prCreated && !disabled;
  // A merged PR has nothing left to approve; re-entering the flow would issue a
  // second merge, which a real git provider rejects.
  const canContinuePr = prCreated && !prDetails.merged;

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
      {canContinuePr && (
        <button
          className={`${styles.actionBtn} ${styles.actionBtnPrimary}`}
          onClick={handleContinuePr}
          disabled={loading}
        >
          {STRINGS.pr.continuePr}
        </button>
      )}
    </div>
  );
}
