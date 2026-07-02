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
