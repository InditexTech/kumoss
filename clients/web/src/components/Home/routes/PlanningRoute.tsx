// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { AssistantAnimation } from "@/components/ui";
import PercentageBarProgress from "../StepperProgress/PercentageBarProgress";
import styles from "../HomeScreen.module.css";

export default function PlanningRoute() {
  return (
    <div className={styles.fullPage}>
      <AssistantAnimation type="speaking" size={180} />
      <PercentageBarProgress />
    </div>
  );
}
