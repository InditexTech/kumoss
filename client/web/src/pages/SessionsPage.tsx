// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { lazy, Suspense } from "react";
import { ErrorBoundary } from "@/components/ui";

const SessionsPageComponent = lazy(
  () => import("@/components/Sessions/SessionsPage"),
);

export default function SessionsPage() {
  return (
    <Suspense>
      <ErrorBoundary>
        <SessionsPageComponent />
      </ErrorBoundary>
    </Suspense>
  );
}
