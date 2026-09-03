// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { useEffect } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { useAuth as useOidcAuth } from "react-oidc-context";
import { isOidcEnabled } from "@/services/auth";
import type { SigninState } from "@/services/auth";

function OidcCallback() {
  const oidc = useOidcAuth();
  const navigate = useNavigate();

  useEffect(() => {
    if (oidc.isLoading) return;
    const state = oidc.user?.state as SigninState | undefined;
    const returnTo = state?.returnTo;
    navigate(returnTo?.startsWith("/") ? returnTo : "/home", {
      replace: true,
    });
  }, [oidc.isLoading, oidc.user, navigate]);

  return null;
}

export default function AuthCallback() {
  if (!isOidcEnabled()) return <Navigate to="/home" replace />;
  return <OidcCallback />;
}
