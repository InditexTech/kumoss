import { useEffect, useRef, useState, type ReactNode } from "react";
import ButtonBase from "@mui/material/ButtonBase";
import CloseIcon from "@mui/icons-material/Close";
import styles from "./Modal.module.css";

interface ModalProps {
  title: ReactNode;
  onClose: () => void;
  children: ReactNode;
}

export default function Modal({ title, onClose, children }: ModalProps) {
  const [pos, setPos] = useState({ x: 0, y: 0 });
  const [dragging, setDragging] = useState(false);
  const dragRef = useRef({ startX: 0, startY: 0, initialX: 0, initialY: 0 });

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const onPointerDown = (e: React.PointerEvent) => {
    if ((e.target as HTMLElement).closest("button")) return;
    dragRef.current = { startX: e.clientX, startY: e.clientY, initialX: pos.x, initialY: pos.y };
    setDragging(true);
    e.currentTarget.setPointerCapture(e.pointerId);
  };

  const onPointerMove = (e: React.PointerEvent) => {
    if (!dragging) return;
    setPos({
      x: dragRef.current.initialX + e.clientX - dragRef.current.startX,
      y: dragRef.current.initialY + e.clientY - dragRef.current.startY,
    });
  };

  const onPointerUp = () => setDragging(false);

  return (
    <div className={styles.overlay} onClick={onClose}>
      <div
        className={styles.card}
        style={{ transform: `translate(${pos.x}px, ${pos.y}px)` }}
        onClick={(e) => e.stopPropagation()}
      >
        <div
          className={`${styles.header} ${dragging ? styles.headerDragging : ""}`}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
        >
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
