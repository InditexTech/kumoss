// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import Typography from "@mui/material/Typography";
import MarkdownText from "@/components/ui/MarkdownText/MarkdownText";
import type { HistoryRole } from "@/types/api";
import styles from "./ChatMessage.module.css";

interface ChatMessageProps {
  role: HistoryRole;
  content: string;
}

export default function ChatMessage({ role, content }: ChatMessageProps) {
  const styleClass =
    role === "user"
      ? styles.user
      : role === "validation"
        ? styles.validation
        : styles.assistant;

  const bullet =
    role === "assistant" ? "○" : role === "validation" ? "◆" : null;

  return (
    <div className={`${styles.message} ${styleClass}`}>
      {bullet && <span className={styles.bullet}>{bullet}</span>}
      <Typography variant="bodyText" component="div" className={styles.content}>
        <MarkdownText content={content} />
      </Typography>
    </div>
  );
}
