// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import React, { createContext, useContext, useEffect, useState } from "react";
import type { StateSetter } from "@/types/ui";
import { STORAGE_KEYS, THEME } from "@/constants";
import { getLocalItem, setLocalItem } from "@/services";

interface ShellContextValue {
  isDark: boolean;
  setIsDark: StateSetter<boolean>;
}

const ShellContext = createContext<ShellContextValue | undefined>(undefined);

export const useShell = () => {
  const ctx = useContext(ShellContext);
  if (!ctx) throw new Error("useShell must be used within ShellProvider");
  return ctx;
};

export const ShellProvider = ({ children }: { children: React.ReactNode }) => {
  const [isDark, setIsDark] = useState(() => {
    const savedTheme = getLocalItem(STORAGE_KEYS.THEME);
    if (!savedTheme) {
      setLocalItem(STORAGE_KEYS.THEME, THEME.LIGHT);
      return false;
    }
    return savedTheme === THEME.DARK;
  });

  useEffect(() => {
    document.documentElement.style.setProperty(
      "color-scheme",
      isDark ? THEME.DARK : THEME.LIGHT,
    );
    setLocalItem(STORAGE_KEYS.THEME, isDark ? THEME.DARK : THEME.LIGHT);
  }, [isDark]);

  return (
    <ShellContext.Provider value={{ isDark, setIsDark }}>
      {children}
    </ShellContext.Provider>
  );
};
