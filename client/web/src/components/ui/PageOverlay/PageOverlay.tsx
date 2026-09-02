// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { useEffect, useRef, type ReactNode } from "react";
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
  const overlayRef = useRef<HTMLDivElement>(null);

  // The overlay is absolutely positioned inside the panel's scrolled
  // content, so it anchors to the content's top. If the panel is scrolled
  // down when it opens, the overlay sits above the viewport and looks
  // truncated — reset the ancestor's scroll while open, restore on close.
  useEffect(() => {
    let scrollable = overlayRef.current?.parentElement ?? null;
    while (scrollable && scrollable.scrollHeight <= scrollable.clientHeight) {
      scrollable = scrollable.parentElement;
    }
    if (!scrollable) return;
    const el = scrollable;
    const prevScrollTop = el.scrollTop;
    const prevOverflowY = el.style.overflowY;
    const prevOverflowAnchor = el.style.overflowAnchor;
    el.scrollTop = 0;
    el.style.overflowY = "hidden";
    el.style.overflowAnchor = "none";
    // Scroll anchoring / late content loads can still nudge the hidden
    // scroller — pin it to the top for as long as the overlay is open.
    const pin = () => {
      if (el.scrollTop !== 0) el.scrollTop = 0;
    };
    el.addEventListener("scroll", pin);
    return () => {
      el.removeEventListener("scroll", pin);
      el.style.overflowY = prevOverflowY;
      el.style.overflowAnchor = prevOverflowAnchor;
      el.scrollTop = prevScrollTop;
    };
  }, []);

  return (
    <div ref={overlayRef} className={styles.overlay} onClick={onClose}>
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
