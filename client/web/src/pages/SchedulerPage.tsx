// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { lazy, Suspense } from "react";
import { ErrorBoundary } from "@/components/ui";

const SchedulerLayout = lazy(() => import("@/components/Scheduler"));

export default function SchedulerPage() {
  return (
    <Suspense>
      <ErrorBoundary>
        <SchedulerLayout />
      </ErrorBoundary>
    </Suspense>
  );
}
