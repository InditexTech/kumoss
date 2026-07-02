import React, { createContext, useContext, useState, useMemo, useCallback } from 'react';
import { MODE } from '@/types/ui';
import type { Mode, ModeContextValue } from '@/types/ui';

const VALID_MODES: readonly Mode[] = Object.values(MODE);
const DEFAULT_MODE: Mode = MODE.GENERATE;

const ModeContext = createContext<ModeContextValue | undefined>(undefined);

export function ModeProvider({ children }: Readonly<{ children: React.ReactNode }>) {
  const [mode, setModeRaw] = useState<Mode>(DEFAULT_MODE);

  const setMode = useCallback((newMode: Mode) => {
    if (VALID_MODES.includes(newMode)) {
      setModeRaw(newMode);
    } else {
      console.warn(`Invalid mode: ${newMode}. Valid modes are: ${VALID_MODES.join(', ')}`);
    }
  }, []);

  const cycleMode = useCallback(() => {
    setModeRaw((prevMode: Mode) => {
      if (prevMode === MODE.GENERATE) return MODE.DRIFT;
      if (prevMode === MODE.DRIFT) return MODE.PARTIAL_DRIFT;
      if (prevMode === MODE.PARTIAL_DRIFT) return MODE.IMPORT;
      return MODE.GENERATE;
    });
  }, []);

  const value: ModeContextValue = useMemo(() => ({
    mode,
    setMode,
    toggleMode: cycleMode,
    cycleMode,
    isGenerateMode: mode === MODE.GENERATE,
    isDriftMode: mode === MODE.DRIFT,
    isPartialDriftMode: mode === MODE.PARTIAL_DRIFT,
    isImportMode: mode === MODE.IMPORT,
    isAnyDriftMode: mode === MODE.DRIFT || mode === MODE.PARTIAL_DRIFT,
  }), [mode, setMode, cycleMode]);

  return (
    <ModeContext.Provider value={value}>
      {children}
    </ModeContext.Provider>
  );
}

export function useMode() {
  const context = useContext(ModeContext);
  if (!context) {
    throw new Error('useMode must be used within a ModeProvider');
  }
  return context;
}

export default ModeContext;
