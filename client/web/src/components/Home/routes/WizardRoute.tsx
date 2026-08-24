// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { AssistantAnimation } from "@/components/ui";
import { useHomeLayoutContext } from "../HomeLayout";
import WizardView from "../WizardView";
import styles from "../HomeScreen.module.css";

export default function WizardRoute() {
  const { wizard } = useHomeLayoutContext();

  const animationType =
    wizard.isLoading && wizard.step === "repository_url"
      ? "speaking"
      : wizard.isLoading
        ? "speaking"
        : "standby";

  return (
    <div className={styles.fullPage}>
      <AssistantAnimation type={animationType} size={180} />
      <WizardView {...wizard} />
    </div>
  );
}
