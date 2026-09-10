// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { useCallback } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { useSession } from "@/contexts/SessionContext";
import { useSessionLoader } from "@/hooks/useSessionLoader";
import { AssistantAnimation } from "@/components/ui";
import { useHomeLayoutContext } from "../HomeLayout";
import ChatHistory from "../ChatHistory/ChatHistory";
import ResultPanel from "../ResultPanel/ResultPanel";
import PrApprovalView from "../PrApprovalView/PrApprovalView";
import type { TabId } from "../ResultPanel/ResultPanel";
import type { PrApprovalStep } from "@/types/ui";
import styles from "../HomeScreen.module.css";

const VALID_TABS: TabId[] = ["plan", "code", "report"];
const VALID_PR_STEPS: PrApprovalStep[] = ["initial", "confirming"];

function parsePrStep(view: string | null): PrApprovalStep | null {
  if (!view?.startsWith("pr-")) return null;
  const step = view.slice(3) as PrApprovalStep;
  return VALID_PR_STEPS.includes(step) ? step : "initial";
}

export default function ResultsRoute() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const { loading, error } = useSessionLoader(sessionId);
  const { wizard, handleContactTeam } = useHomeLayoutContext();
  const { session, updatePrDetails } = useSession();

  const [searchParams, setSearchParams] = useSearchParams();
  const rawTab = searchParams.get("tab") as TabId | null;
  const resultTab: TabId = rawTab && VALID_TABS.includes(rawTab) ? rawTab : "report";
  const prStep = parsePrStep(searchParams.get("view"));

  const handleTabChange = useCallback(
    (tab: TabId) => {
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev);
        next.set("tab", tab);
        next.delete("detail");
        next.delete("resource");
        return next;
      });
    },
    [setSearchParams],
  );

  const handleResetToReport = useCallback(
    () => handleTabChange("report"),
    [handleTabChange],
  );

  const handlePrStepChange = useCallback(
    (step: PrApprovalStep) => {
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev);
        next.set("view", `pr-${step}`);
        return next;
      }, { replace: true });
    },
    [setSearchParams],
  );

  const handleBackToResult = useCallback(() => {
    const currentStep = parsePrStep(searchParams.get("view"));
    if (currentStep) updatePrDetails({ lastPrStep: currentStep });
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      next.delete("view");
      return next;
    }, { replace: true });
  }, [searchParams, setSearchParams, updatePrDetails]);

  const hasArtifacts = Boolean(session.code || session.terraform_report);

  if (loading) return <div className={styles.leftSide}>Loading session…</div>;
  if (error) return <div className={styles.leftSide}>Error: {error}</div>;

  if (prStep) {
    const isApplyBlocked = !!session.is_blocked;
    return (
      <div className={styles.fullPage}>
        <AssistantAnimation
          type={isApplyBlocked ? "error" : "standby"}
          size={isApplyBlocked ? 220 : 180}
        />
        <PrApprovalView
          step={prStep}
          onStepChange={handlePrStepChange}
          onApprove={wizard.applyAfterPr}
          onBackToReport={handleBackToResult}
          onContactTeam={handleContactTeam}
        />
      </div>
    );
  }

  if (!hasArtifacts) {
    return (
      <div className={`${styles.leftSide} ${styles.leftSideChat}`}>
        <div className={`${styles.chatFull} ${styles.chatCentered}`}>
          <ChatHistory
            onIterate={wizard.iterate}
            onResetToReport={handleResetToReport}
            hideActions
          />
        </div>
      </div>
    );
  }

  return (
    <>
      <div className={`${styles.leftSide} ${styles.leftSideChat}`}>
        <div className={styles.chatFull}>
          <ChatHistory
            onIterate={wizard.iterate}
            onResetToReport={handleResetToReport}
            isSplitView
          />
        </div>
      </div>
      <div className={styles.resultSlider}>
        <ResultPanel tab={resultTab} onTabChange={handleTabChange} />
      </div>
    </>
  );
}
