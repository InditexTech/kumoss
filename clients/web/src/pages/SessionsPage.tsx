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
