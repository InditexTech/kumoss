import { lazy } from "react";
import { Routes, Route, Navigate } from "react-router-dom";
import HomeLayout from "@/components/Home/HomeLayout";
import AdminPage from "@/pages/AdminPage";
import SessionsPage from "@/pages/SessionsPage";

const WizardRoute = lazy(() => import("@/components/Home/routes/WizardRoute"));
const PlanningRoute = lazy(
  () => import("@/components/Home/routes/PlanningRoute"),
);
const ResultsRoute = lazy(
  () => import("@/components/Home/routes/ResultsRoute"),
);
const ApplyResultsRoute = lazy(
  () => import("@/components/Home/routes/ApplyResultsRoute"),
);
const UserPage = lazy(() => import("@/pages/UserPage"));

export default function AppRouter() {
  return (
    <Routes>
      <Route path="/home" element={<HomeLayout />}>
        <Route index element={<WizardRoute />} />
        <Route path="planning" element={<PlanningRoute />} />
        <Route path="results/:sessionId" element={<ResultsRoute />} />
        <Route path="apply-results/:sessionId" element={<ApplyResultsRoute />} />
      </Route>
      <Route path="/admin/*" element={<AdminPage />} />
      <Route path="/user" element={<UserPage />} />
      <Route path="/user/sessions" element={<SessionsPage />} />
      <Route path="/sessions" element={<Navigate to="/user/sessions" replace />} />
      <Route path="/home/sessions" element={<Navigate to="/user/sessions" replace />} />
      <Route path="/*" element={<Navigate to="/home" replace />} />
    </Routes>
  );
}
