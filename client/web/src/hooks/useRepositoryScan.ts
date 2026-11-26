// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { useState, useCallback } from "react";
import { parseRepository } from "@/services/core/iac_code";

/**
 * What a scan found: the resolved clone URL, its root modules, and the
 * project identifier the user typed (to send on the session's first call).
 */
export interface RepositoryScan {
  repoUrl: string;
  projectIdentifier: string;
  roots: string[];
}

/**
 * Lists a repository's Terraform root modules for the wizard's
 * repository step. The core resolves what the user typed (a repository
 * name or a full URL) through the mapping service first, and every later
 * call must use the `repoUrl` it answers, not the raw input.
 */
export function useRepositoryScan() {
  const [scanPaths, setScanPaths] = useState<string[]>([]);
  const [scanLoading, setScanLoading] = useState(false);
  const [scanError, setScanError] = useState<string | null>(null);

  /** Resolves and scans `input`; throws when either fails. */
  const scan = useCallback(async (input: string): Promise<RepositoryScan> => {
    setScanLoading(true);
    setScanError(null);
    try {
      const parsed = await parseRepository(input);
      setScanPaths(parsed.roots);
      return {
        repoUrl: parsed.repo_url,
        projectIdentifier: parsed.project_identifier,
        roots: parsed.roots,
      };
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
