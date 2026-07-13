// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { useRef, useEffect, useCallback, useState } from "react";
import ArrowUpwardIcon from "@mui/icons-material/ArrowUpward";
import { useSession } from "@/contexts/SessionContext";
import { STRINGS } from "@/constants/strings";
import ChatMessage from "./ChatMessage";
import ChatActionBar from "./ChatActionBar";
import styles from "./ChatHistory.module.css";

interface ChatHistoryProps {
  onIterate: (query: string) => void;
  onResetToReport: () => void;
  disabled?: boolean;
  isApplyResult?: boolean;
  isSplitView?: boolean;
}

export default function ChatHistory({ onIterate, onResetToReport, disabled, isApplyResult, isSplitView }: ChatHistoryProps) {
  const { session } = useSession();
  const messages = (session.full_history ?? []).filter(e => e.role !== "validation");
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const [hasText, setHasText] = useState(false);

  useEffect(() => {
    requestAnimationFrame(() => {
      bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    });
  }, [messages.length]);

  const handleSubmit = useCallback(() => {
    const value = inputRef.current?.value.trim();
    if (!value) return;
    inputRef.current!.value = "";
    setHasText(false);
    onIterate(value);
  }, [onIterate]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (e.key === "Enter") handleSubmit();
    },
    [handleSubmit],
  );

  return (
    <div className={styles.container}>
      <div className={`${styles.messageList} ${isSplitView ? styles.messageListSplit : ""}`}>
        <div className={styles.spacer} />
        {messages.map((entry, i) => (
          <ChatMessage key={`${entry.role}-${i}`} role={entry.role} content={entry.content} />
        ))}
        <div ref={bottomRef} />
      </div>

      <ChatActionBar onResetToReport={onResetToReport} disabled={disabled} isApplyResult={isApplyResult} />

      <div className={styles.inputBar}>
        <input
          ref={inputRef}
          type="text"
          className={styles.input}
          placeholder={STRINGS.chat.followUpPlaceholder}
          onKeyDown={handleKeyDown}
          onChange={(e) => setHasText(e.target.value.trim().length > 0)}
          maxLength={500}
          disabled={disabled}
          aria-label="Follow-up question"
        />
        <button
          className={styles.sendBtn}
          onClick={handleSubmit}
          disabled={disabled || !hasText}
          aria-label="Send message"
        >
          <ArrowUpwardIcon fontSize="small" />
        </button>
      </div>
    </div>
  );
}
