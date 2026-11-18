// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { useState, useCallback } from "react";
import { parseRepository } from "@/services/core/iac_code";

/**
 * Lists a repository's Terraform root modules for the wizard's
 * repository step. The URL the user typed is used as is: no lookup
 * service sits in front of it.
 */
export function useRepositoryScan() {
  const [scanPaths, setScanPaths] = useState<string[]>([]);
  const [scanLoading, setScanLoading] = useState(false);
  const [scanError, setScanError] = useState<string | null>(null);

  /** The root module paths of `repoUrl`; throws when the scan fails. */
  const scan = useCallback(async (repoUrl: string): Promise<string[]> => {
    setScanLoading(true);
    setScanError(null);
    try {
      const parsed = await parseRepository(repoUrl);
      setScanPaths(parsed.roots);
      return parsed.roots;
    } finally {
      setScanLoading(false);
    }
  }, []);

  const resetScan = useCallback(() => {
    setScanPaths([]);
    setScanLoading(false);
    setScanError(null);
  }, []);

  return {
    scanPaths,
    scanLoading,
    scanError,
    setScanError,
    scan,
    resetScan,
  } as const;
}
