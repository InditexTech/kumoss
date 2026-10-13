// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import Fade from "@mui/material/Fade";
import { useAssistantMsg } from "@/contexts/AssistantMsgContext";
import { usePhaseMessages } from "@/hooks/usePhaseMessages";
import { PHASE } from "@/types/ui";
import PhaseMessages from "./PhaseMessages";
import styles from "./PercentageBarProgress.module.css";

const GENERATE_PERCENTAGES: Record<string, number> = {
  STARTED: 0,
  FILTERING: 30,
  RECONCILING: 45,
  GENERATING: 60,
  VALIDATING: 80,
  APPLY: 90,
  REPORT: 100,
  COMPLETED: 100,
  UNCOMPLETED: 100,
};

const APPLY_PERCENTAGES: Record<string, number> = {
  STARTED: 0,
  FILTERING: 30,
  RECONCILING: 45,
  GENERATING: 60,
  VALIDATING: 80,
  APPLY: 90,
  REPORT: 100,
  COMPLETED: 100,
  UNCOMPLETED: 100,
};

export default function PercentageBarProgress() {
  const { assistantMsgState } = useAssistantMsg();
  const { latestByPhase, currentPhase, isApplyMode } = usePhaseMessages();

  const { sseStatus } = assistantMsgState;

  const isComplete =
    currentPhase === PHASE.COMPLETE || currentPhase === PHASE.FINALIZING;

  const percentages = isApplyMode ? APPLY_PERCENTAGES : GENERATE_PERCENTAGES;
  const pct = isComplete ? 100 : (percentages[sseStatus] ?? 0);

  const latestMessage = (() => {
    const phases = [PHASE.REPORT, PHASE.RUNNING, PHASE.INIT] as const;
    for (const p of phases) {
      const msg = latestByPhase[p];
      if (msg) return msg;
    }
    return null;
  })();

  const fillCls = [styles.fill];
  if (!isComplete) fillCls.push(styles.fillActive);

  return (
    <Fade in timeout={800}>
      <div className={styles.container}>
        <div className={styles.track}>
          <div className={fillCls.join(" ")} style={{ width: `${pct}%` }} />
        </div>

        <div className={styles.messageArea}>
          <PhaseMessages
            latestMessage={latestMessage}
            isActive={!isComplete}
            className={styles.messageText}
          />
        </div>
      </div>
    </Fade>
  );
}
