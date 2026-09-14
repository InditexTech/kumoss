// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { useEffect, useRef } from "react";
import { useParams } from "react-router-dom";
import { useSessionLoader } from "@/hooks/useSessionLoader";
import { STRINGS } from "@/constants/strings";
import { useHomeLayoutContext } from "../HomeLayout";
import ChatHistory from "../ChatHistory/ChatHistory";
import ApplyResultView from "../ApplyResultView/ApplyResultView";
import styles from "../HomeScreen.module.css";

export default function ApplyResultsRoute() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const { loading, error, inProgress } = useSessionLoader(sessionId);
  const { wizard } = useHomeLayoutContext();
  const resumedRef = useRef<string | null>(null);

  // The apply writes its report only when it ends, so a still-running round
  // has nothing to show here: rejoin the stream and let it land back on this
  // route once it settles. The ref — not the dep array — keeps this to one
  // resume per session, since `wizard` is rebuilt on every render.
  useEffect(() => {
    if (inProgress && resumedRef.current !== inProgress.sessionId) {
      resumedRef.current = inProgress.sessionId;
      wizard.resume(inProgress);
    }
  }, [inProgress, wizard]);

  if (loading) return <div className={styles.leftSide}>Loading session…</div>;
  if (inProgress) {
    return (
      <div className={styles.leftSide}>{STRINGS.planning.stillRunning}</div>
    );
  }
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
