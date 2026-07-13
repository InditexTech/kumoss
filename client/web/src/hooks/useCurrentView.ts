// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { useLocation } from "react-router-dom";
import type { HomeView } from "@/types/ui";

const VIEW_MAP: Record<string, HomeView> = {
  planning: "planning",
  results: "result",
  "apply-results": "apply-results",
};

export function useCurrentView(): HomeView | null {
  const { pathname } = useLocation();

  if (!pathname.startsWith("/home")) return null;

  const segment = pathname.split("/")[2];
  if (!segment) return "wizard";

  return VIEW_MAP[segment] ?? null;
}
