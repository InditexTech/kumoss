// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import type { ReactNode } from "react";
import ButtonBase from "@mui/material/ButtonBase";
import CloseIcon from "@mui/icons-material/Close";
import styles from "./PageOverlay.module.css";

interface PageOverlayProps {
  title: ReactNode;
  onClose: () => void;
  children: ReactNode;
}

export default function PageOverlay({
  title,
  onClose,
  children,
}: PageOverlayProps) {
  return (
    <div className={styles.overlay} onClick={onClose}>
      <div
        className={styles.content}
        data-detail-content
        onClick={(e) => e.stopPropagation()}
      >
        <div className={styles.header}>
          <h3 className={styles.title}>{title}</h3>
          <ButtonBase onClick={onClose} className={styles.close}>
            <CloseIcon style={{ fontSize: "18px" }} />
          </ButtonBase>
        </div>
        {children}
      </div>
    </div>
  );
}
