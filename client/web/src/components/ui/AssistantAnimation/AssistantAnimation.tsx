// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { useShell } from "@/contexts/ShellContext";
import { AssistantAnimatedIcon } from "./assistant-animated-icon/AssistantAnimatedIcon.tsx";
import styles from "./AssistantAnimation.module.css";

interface Props {
  type: "icon" | "listening" | "speaking" | "loading" | "standby" | "error";
  size: number;
  background?: boolean;
}

export const AssistantAnimation = ({ type, size, background }: Props) => {
  const { isDark } = useShell();

  return (
    <div className={background ? styles.background : ""}>
      <AssistantAnimatedIcon
        theme={isDark ? "white" : "blue"}
        phase={type}
        width={size}
        height={size}
      />
    </div>
  );
};
