import { useState, useCallback } from "react";
import { resolveProject } from "@/services/mapper/mapper";
import { scanRepository } from "@/services/core/iac_code";

export interface ResolveResult {
  repoUrl: string;
  project: string | null;
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
        const scan = await scanRepository(resolved.repo_url);
        setScanPaths(scan.paths);
        return {
          repoUrl: resolved.repo_url,
          project: resolved.project ?? null,
          paths: scan.paths,
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
