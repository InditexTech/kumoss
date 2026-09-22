// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { useState, useCallback } from "react";
import { resolveProject } from "@/services/mapper/mapper";
import { parseRepository } from "@/services/core/iac_code";
import type { TerraformProvider } from "@/types/api";

/**
 * What the mapper knows about an identifier.
 *
 * `provider` and `scopeId` are best effort: null means the mapper does
 * not know, so the wizard must ask. A non-null value skips its step.
 */
export interface ResolveResult {
  repoUrl: string;
  identifier: string;
  provider: TerraformProvider | null;
  scopeId: string | null;
  paths: string[];
}

export function useMapperResolution() {
  const [scanPaths, setScanPaths] = useState<string[]>([]);
  const [mapperLoading, setMapperLoading] = useState(false);
  const [mapperError, setMapperError] = useState<string | null>(null);

  const resolveAndScan = useCallback(
    async (identifier: string): Promise<ResolveResult> => {
      setMapperLoading(true);
      setMapperError(null);
      try {
        const resolved = await resolveProject({ identifier });
        const parsed = await parseRepository(resolved.repo_url);
        setScanPaths(parsed.roots);
        return {
          repoUrl: resolved.repo_url,
          identifier: resolved.identifier,
          provider: resolved.terraform_provider ?? null,
          // Deliberately unvalidated. The typed-scope pattern is a
          // human-typo guard that an OCI compartment OCID already
          // fails; applying it here would reject a correct answer and
          // drop the user on a step where they cannot type a valid one
          // either. The mapper is a trusted internal service and the
          // contract bounds this to 1..1024 characters.
          scopeId: resolved.scope_id ?? null,
          paths: parsed.roots,
        };
      } finally {
        setMapperLoading(false);
      }
    },
    [],
  );

  const resetMapper = useCallback(() => {
    setScanPaths([]);
    setMapperLoading(false);
    setMapperError(null);
  }, []);

  return {
    scanPaths,
    mapperLoading,
    mapperError,
    setMapperError,
    resolveAndScan,
    resetMapper,
  } as const;
}
