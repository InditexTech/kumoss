// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { useParams } from "react-router-dom";
import { useSessionLoader } from "@/hooks/useSessionLoader";
import { useHomeWizard } from "../useHomeWizard";
import ChatHistory from "../ChatHistory/ChatHistory";
import ApplyResultView from "../ApplyResultView/ApplyResultView";
import styles from "../HomeScreen.module.css";

export default function ApplyResultsRoute() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const { loading, error } = useSessionLoader(sessionId);
  const wizard = useHomeWizard();

  if (loading) return <div className={styles.leftSide}>Loading session…</div>;
  if (error) return <div className={styles.leftSide}>Error: {error}</div>;

  return (
    <>
      <div className={`${styles.leftSide} ${styles.leftSideChat}`}>
        <div className={styles.chatFull}>
          <ChatHistory
            onIterate={wizard.iterate}
            onResetToReport={() => {}}
            isApplyResult
            isSplitView
          />
        </div>
      </div>
      <div className={styles.resultSlider}>
        <ApplyResultView />
      </div>
    </>
  );
}
