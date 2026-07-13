// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { Navigate, Outlet } from "react-router-dom";
import { useAuth } from "@/contexts/AuthContext";

export default function RequireAuth() {
  const { isAuthenticated } = useAuth();

  if (!isAuthenticated) return <Navigate to="/" replace />;

  return <Outlet />;
}
