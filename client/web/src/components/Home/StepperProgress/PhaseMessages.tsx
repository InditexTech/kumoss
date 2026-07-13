// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { useState, useEffect, useRef } from "react";
import Typography from "@mui/material/Typography";
import styles from "./PercentageBarProgress.module.css";

const SLIDE_OUT_MS = 500;

interface PhaseMessagesProps {
  latestMessage: string | null;
  isActive: boolean;
  className?: string;
}

export default function PhaseMessages({
  latestMessage,
  isActive,
  className,
}: PhaseMessagesProps) {
  const [displayed, setDisplayed] = useState<string | null>(null);
  const [phase, setPhase] = useState<"in" | "out" | "idle">("idle");
  const timeoutRef = useRef<ReturnType<typeof setTimeout>>();

  useEffect(() => {
    if (!latestMessage || latestMessage === displayed) return;

    clearTimeout(timeoutRef.current);

    if (!displayed) {
      setDisplayed(latestMessage);
      setPhase("in");
      return;
    }

    setPhase("out");
    timeoutRef.current = setTimeout(() => {
      setDisplayed(latestMessage);
      setPhase("in");
    }, SLIDE_OUT_MS);

    return () => clearTimeout(timeoutRef.current);
  }, [latestMessage, displayed]);

  if (!displayed) return null;

  const animClass = !isActive
    ? ""
    : phase === "in"
      ? styles.messageIn
      : phase === "out"
        ? styles.messageOut
        : "";

  return (
    <div className={styles.messageArea}>
      <Typography
        key={displayed}
        variant="subtitle2"
        component="span"
        className={`${className ?? styles.messageItem} ${animClass}`}
      >
        {displayed}
      </Typography>
    </div>
  );
}
