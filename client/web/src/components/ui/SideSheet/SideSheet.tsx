// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { useEffect, type ReactNode } from "react";
import ButtonBase from "@mui/material/ButtonBase";
import Typography from "@mui/material/Typography";
import CloseIcon from "@mui/icons-material/Close";
import styles from "./SideSheet.module.css";

interface SideSheetProps {
  isVisible: boolean;
  onClose: () => void;
  title: ReactNode;
  children: ReactNode;
}

export default function SideSheet({
  isVisible,
  onClose,
  title,
  children,
}: SideSheetProps) {
  useEffect(() => {
    if (!isVisible) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    const onClick = (e: MouseEvent) => {
      if (!(e.target as HTMLElement).closest("[data-detail-content]")) {
        onClose();
      }
    };
    document.addEventListener("keydown", onKey);
    const rafId = requestAnimationFrame(() => {
      document.addEventListener("mousedown", onClick);
    });
    return () => {
      cancelAnimationFrame(rafId);
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onClick);
    };
  }, [isVisible, onClose]);

  if (!isVisible) return null;

  return (
    <div className={styles.overlay}>
      <div
        className={styles.content}
        data-detail-content
        onClick={(e) => e.stopPropagation()}
      >
        <div className={styles.header}>
          <Typography variant="subtitle1" component="h3" className={styles.title}>{title}</Typography>
          <ButtonBase onClick={onClose} className={styles.close}>
            <CloseIcon style={{ fontSize: "18px" }} />
          </ButtonBase>
        </div>
        {children}
      </div>
    </div>
  );
}
