// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { Suspense, useRef, useCallback, useEffect } from "react";
import { Outlet, useLocation, useOutletContext } from "react-router-dom";
import { SupportButton, ErrorBoundary } from "@/components/ui";
import { useCurrentView } from "@/hooks/useCurrentView";
import { useHomeWizard } from "./useHomeWizard";
import type { HomeView } from "@/types/ui";
import styles from "./HomeScreen.module.css";

interface HomeLayoutContext {
  view: HomeView | null;
  isSplitView: boolean;
  handleContactTeam: () => void;
  wizard: ReturnType<typeof useHomeWizard>;
}

export default function HomeLayout() {
  const view = useCurrentView();
  const wizard = useHomeWizard();
  const resetWizard = wizard.reset;
  const location = useLocation();
  const supportBtnRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (location.state?.resetWizard) {
      resetWizard();
    }
  }, [location.state?.resetWizard, resetWizard]);

  const handleContactTeam = useCallback(() => {
    const btn = supportBtnRef.current?.querySelector("button");
    btn?.click();
  }, []);

  const isSplitView = view === "result" || view === "apply-results";

  return (
    <div className={styles.layout}>
      <div
        className={`${styles.container} ${isSplitView ? styles.containerSplit : ""}`}
      >
        <Suspense>
          <ErrorBoundary>
            <Outlet context={{ view, isSplitView, handleContactTeam, wizard }} />
          </ErrorBoundary>
        </Suspense>
        <div ref={supportBtnRef} style={{ display: "none" }}>
          <SupportButton />
        </div>
      </div>
    </div>
  );
}

export function useHomeLayoutContext() {
  return useOutletContext<HomeLayoutContext>();
}
