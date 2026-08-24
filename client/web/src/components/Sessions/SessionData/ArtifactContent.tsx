// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { useState, useMemo, useEffect, useCallback } from "react";
import Typography from "@mui/material/Typography";
import { useSearchParams } from "react-router-dom";
import { fetchArtifactContent } from "@/services/core/sessions";
import { useMode } from "@/contexts/ModeContext";
import type {
  ArtifactRef,
  CodeChangeRef,
  OperationType,
  RoundDetail,
} from "@/types/api";
import type { TerraformReport } from "@/types";
import {
  ChangesTable,
  ChangeDetail,
  PotentialImpactCard,
  ImpactDetail,
  EstimatedCostsCard,
  CostsDetail,
} from "@/components/Home";
import type { FilterId, DetailView } from "@/components/Home";
import { CodeBlock } from "@/components/ui";
import styles from "./ArtifactContent.module.css";

export type ArtifactKind = "report" | "plan" | "change";

interface ArtifactContentProps {
  kind: ArtifactKind;
  artifact: ArtifactRef;
  round: RoundDetail;
  operation: OperationType;
}

export function artifactLabel(kind: ArtifactKind, artifact: ArtifactRef): string {
  switch (kind) {
    case "report":
      return "Report";
    case "plan":
      return "Terraform Plan";
    case "change":
      return (artifact as CodeChangeRef).file_name;
  }
}

function getLanguage(kind: ArtifactKind, artifact: ArtifactRef): string {
  if (artifact.content_type?.includes("json")) return "json";
  if (kind === "plan") return "hcl";
  if (kind === "change" && (artifact as CodeChangeRef).file_name.endsWith(".tf"))
    return "hcl";
  return "plaintext";
}

export default function ArtifactContent({
  kind,
  artifact,
  round,
  operation,
}: Readonly<ArtifactContentProps>) {
  const [content, setContent] = useState<string | null>(null);
  const [files, setFiles] = useState<Record<string, string> | null>(null);
  const [loading, setLoading] = useState(true);
  const { setMode } = useMode();

  const [searchParams, setSearchParams] = useSearchParams();

  const VALID_DETAILS: DetailView[] = ["impact", "costs", "change"];
  const VALID_FILTERS: FilterId[] = ["all", "create", "update", "delete", "recreate"];

  const rawDetail = searchParams.get("detail") as DetailView;
  const activeDetail: DetailView =
    rawDetail && VALID_DETAILS.includes(rawDetail) ? rawDetail : null;

  const resourceParam = searchParams.get("resource");

  const rawFilter = searchParams.get("filter") as FilterId;
  const activeFilter: FilterId =
    rawFilter && VALID_FILTERS.includes(rawFilter) ? rawFilter : "all";

  const activeFile = searchParams.get("file") || "";

  const setActiveDetail = useCallback(
    (detail: DetailView, resourceName?: string) => {
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev);
        if (detail) {
          next.set("detail", detail);
        } else {
          next.delete("detail");
        }
        if (resourceName) {
          next.set("resource", resourceName);
        } else {
          next.delete("resource");
        }
        return next;
      });
    },
    [setSearchParams],
  );

  const setActiveFilter = useCallback(
    (filter: FilterId) => {
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev);
        if (filter && filter !== "all") {
          next.set("filter", filter);
        } else {
          next.delete("filter");
        }
        return next;
      });
    },
    [setSearchParams],
  );

  const setActiveFile = useCallback(
    (file: string) => {
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev);
        if (file) {
          next.set("file", file);
        } else {
          next.delete("file");
        }
        return next;
      });
    },
    [setSearchParams],
  );

  // Load content: a code change loads every file of its round so the
  // viewer can offer file tabs; report/plan load their single artifact.
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setContent(null);
    setFiles(null);

    (async () => {
      try {
        if (kind === "change") {
          const contents = await Promise.all(
            round.code_changes.map((c) => fetchArtifactContent(c.url)),
          );
          if (cancelled) return;
          const record: Record<string, string> = {};
          round.code_changes.forEach((c, i) => {
            record[c.file_name] = contents[i];
          });
          setFiles(record);
        } else {
          const text = await fetchArtifactContent(artifact.url);
          if (cancelled) return;
          setContent(text);
        }
      } catch {
        // leave content/files null → error state
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [kind, artifact.url, round]);

  // The session's operation drives the report rendering mode; no more
  // sniffing the report JSON for marker keys.
  useEffect(() => {
    if (kind === "report") {
      setMode(
        operation === "drift"
          ? "drift"
          : operation === "import"
            ? "import"
            : "generate",
      );
    }
    return () => setMode("generate");
  }, [kind, operation, setMode]);

  const reportData: TerraformReport | null = useMemo(() => {
    if (kind !== "report" || !content) return null;
    try {
      return JSON.parse(content);
    } catch {
      return null;
    }
  }, [kind, content]);

  const selectedChange = useMemo(() => {
    if (activeDetail !== "change" || !resourceParam || !reportData?.detailed_changes) return null;
    return reportData.detailed_changes.find((c) => c.name === resourceParam) ?? null;
  }, [activeDetail, resourceParam, reportData?.detailed_changes]);

  const fileNames = files ? Object.keys(files) : [];
  const clickedFileName =
    kind === "change" ? (artifact as CodeChangeRef).file_name : "";
  const effectiveActiveFile =
    activeFile || clickedFileName || (fileNames.length > 0 ? fileNames[0] : "");

  if (loading) {
    return <Typography variant="subtitle2" component="div" className={styles.loading}>Loading artifact...</Typography>;
  }

  if (kind === "change") {
    if (!files || fileNames.length === 0) {
      return <Typography variant="subtitle2" component="div" className={styles.loading}>Failed to load artifact</Typography>;
    }
    return (
      <CodeBlock
        files={files}
        activeFile={effectiveActiveFile}
        onFileChange={setActiveFile}
        showLineNumbers
        height="calc(100vh - 200px)"
      />
    );
  }

  if (content === null) {
    return <Typography variant="subtitle2" component="div" className={styles.loading}>Failed to load artifact</Typography>;
  }

  if (kind === "report" && reportData) {
    return (
      <div className={styles.reportContainer}>
        {reportData.execution_summary && (
          <div className={styles.executionSummary}>
            <Typography variant="label" className={styles.executionSummaryLabel}>Execution Summary</Typography>
            <Typography variant="bodyText" className={styles.executionSummaryText}>
              {reportData.execution_summary}
            </Typography>
          </div>
        )}
        {reportData.potential_impact && (
          <div
            className={styles.reportCard}
            onClick={() => setActiveDetail("impact")}
            role="button"
            tabIndex={0}
            onKeyDown={(e) =>
              e.key === "Enter" && setActiveDetail("impact")
            }
          >
            <PotentialImpactCard impact={reportData.potential_impact} />
          </div>
        )}
        {reportData.estimated_costs && (
          <div
            className={styles.reportCard}
            onClick={() => setActiveDetail("costs")}
            role="button"
            tabIndex={0}
            onKeyDown={(e) =>
              e.key === "Enter" && setActiveDetail("costs")
            }
          >
            <EstimatedCostsCard costs={reportData.estimated_costs} />
          </div>
        )}
        <ChangesTable
          changes={reportData.detailed_changes ?? []}
          activeFilter={activeFilter}
          setActiveFilter={setActiveFilter}
          onSelectChange={(change) => {
            setActiveDetail("change", change.name);
          }}
        />

        {activeDetail === "impact" && reportData.potential_impact && (
          <ImpactDetail
            impact={reportData.potential_impact}
            onClose={() => setActiveDetail(null)}
          />
        )}
        {activeDetail === "costs" && reportData.estimated_costs && (
          <CostsDetail
            costs={reportData.estimated_costs}
            onClose={() => setActiveDetail(null)}
          />
        )}
        {activeDetail === "change" && selectedChange && (
          <ChangeDetail
            change={selectedChange}
            onClose={() => setActiveDetail(null)}
          />
        )}
      </div>
    );
  }

  return (
    <CodeBlock
      code={content}
      language={getLanguage(kind, artifact)}
      showLineNumbers
      height="calc(100vh - 200px)"
    />
  );
}
