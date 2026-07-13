// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { useRef, useCallback } from "react";

const DRAG_THRESHOLD = 5;

export default function useDragScroll<T extends HTMLElement = HTMLElement>() {
  const ref = useRef<T>(null);
  const state = useRef({ dragging: false, startX: 0, scrollLeft: 0, didDrag: false });

  const onPointerDown = useCallback((e: React.PointerEvent) => {
    const el = ref.current;
    if (!el || e.button !== 0) return;
    const target = e.target as HTMLElement;
    if (target.closest("button, a, [data-no-drag]")) return;
    el.setPointerCapture(e.pointerId);
    state.current = { dragging: true, startX: e.clientX, scrollLeft: el.scrollLeft, didDrag: false };
    el.style.cursor = "grabbing";
    el.style.userSelect = "none";
  }, []);

  const onPointerMove = useCallback((e: React.PointerEvent) => {
    const s = state.current;
    if (!s.dragging) return;
    const dx = e.clientX - s.startX;
    if (Math.abs(dx) > DRAG_THRESHOLD) s.didDrag = true;
    ref.current!.scrollLeft = s.scrollLeft - dx;
  }, []);

  const onPointerUp = useCallback(() => {
    state.current.dragging = false;
    const el = ref.current;
    if (el) {
      el.style.cursor = "";
      el.style.userSelect = "";
    }
  }, []);

  const onClickCapture = useCallback((e: React.MouseEvent) => {
    if (state.current.didDrag) {
      e.stopPropagation();
      e.preventDefault();
      state.current.didDrag = false;
    }
  }, []);

  return { ref, onPointerDown, onPointerMove, onPointerUp, onClickCapture };
}
