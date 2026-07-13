// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { lazy, Suspense } from "react";
import { ErrorBoundary } from "@/components/ui";

const AdminLayout = lazy(() => import("@/components/Admin/AdminLayout"));

export default function AdminPage() {
  return (
    <Suspense>
      <ErrorBoundary>
        <AdminLayout />
      </ErrorBoundary>
    </Suspense>
  );
}
