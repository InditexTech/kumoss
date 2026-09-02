// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { useState, useCallback, useRef } from "react";
import { resolveProject } from "@/services/mapper/mapper";
import { parseRepository } from "@/services/core/iac_code";

export interface ResolveResult {
  repoUrl: string;
  project: string | null;
  paths: string[];
}

export function useMapperResolution() {
  const [scanPaths, setScanPaths] = useState<string[]>([]);
  const [mapperLoading, setMapperLoading] = useState(false);
  const [mapperError, setMapperError] = useState<string | null>(null);
  const requestIdRef = useRef(0);

  const resolveAndScan = useCallback(
    async (identifier: string): Promise<ResolveResult | null> => {
      const requestId = ++requestIdRef.current;
      setMapperLoading(true);
      setMapperError(null);
      try {
        const resolved = await resolveProject({ identifier });
        if (requestId !== requestIdRef.current) return null;
        const parsed = await parseRepository(resolved.repo_url);
        if (requestId !== requestIdRef.current) return null;
        setScanPaths(parsed.roots);
        return {
          repoUrl: resolved.repo_url,
          project: resolved.project ?? null,
          paths: parsed.roots,
        };
      } catch (error) {
        if (requestId !== requestIdRef.current) return null;
        throw error;
      } finally {
        if (requestId === requestIdRef.current) {
          setMapperLoading(false);
        }
      }
    },
    [],
  );

  const resetMapper = useCallback(() => {
    requestIdRef.current += 1;
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
