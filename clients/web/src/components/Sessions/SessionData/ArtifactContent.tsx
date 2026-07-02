import { useState, useMemo, useEffect, useCallback } from "react";
import Typography from "@mui/material/Typography";
import { useSearchParams } from "react-router-dom";
import { fetchArtifactContent } from "@/services/core/sessions";
import { useMode } from "@/contexts/ModeContext";
import type { AdminOperationItem } from "@/types/api";
import type { TerraformReport } from "@/types";
import {
  PlanSummaryBar,
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

interface ArtifactContentProps {
  operation: AdminOperationItem;
}

function processFiles(input: string): Record<string, string> {
  if (!input) return {};
  const fileRegex = /<([\w./\\-]+)>([\s\S]*?)<\/\1>/g;
  const files: Record<string, string> = {};
  let match: RegExpExecArray | null;
  while ((match = fileRegex.exec(input)) !== null) {
    const fileName = match[1];
    if (fileName !== "Terraform_Plan") {
      files[fileName] = match[2].trim() + "\n\n";
    }
  }
  return files;
}

function getLanguage(
  artifactType: string | null,
  contentType: string | null,
): string {
  if (contentType?.includes("json")) return "json";
  if (artifactType?.includes("terraform") || artifactType?.includes("plan"))
    return "hcl";
  return "plaintext";
}

export function formatArtifactLabel(artifactType: string | null): string {
  if (!artifactType) return "Artifact";
  return artifactType
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

export default function ArtifactContent({
  operation,
}: Readonly<ArtifactContentProps>) {
  const [content, setContent] = useState<string | null>(null);
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

  const loadContent = useCallback(async () => {
    if (!operation.blob_url) {
      setContent(null);
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const text = await fetchArtifactContent(operation.blob_url);
      setContent(text);
    } catch {
      setContent(null);
    } finally {
      setLoading(false);
    }
  }, [operation.blob_url]);

  useEffect(() => {
    loadContent();
  }, [loadContent]);

  useEffect(() => {
    if (operation.artifact_type === "terraform_report" && content) {
      try {
        const parsed: Record<string, unknown> = JSON.parse(content);
        if (parsed.import_summary) {
          setMode("import");
        } else if (parsed.remediated_resources) {
          setMode("drift");
        } else {
          setMode("generate");
        }
      } catch {
        // ignore parse errors
      }
    }
    return () => setMode("generate");
  }, [content, operation.artifact_type, setMode]);

  const isReport = operation.artifact_type === "terraform_report";
  const isGeneratedCode = operation.artifact_type === "generated_code";
  const files = isGeneratedCode ? processFiles(content || "") : null;
  const fileNames = files ? Object.keys(files) : [];

  const reportData: TerraformReport | null = useMemo(() => {
    if (!isReport || !content) return null;
    try {
      return JSON.parse(content);
    } catch {
      return null;
    }
  }, [isReport, content]);

  const selectedChange = useMemo(() => {
    if (activeDetail !== "change" || !resourceParam || !reportData?.detailed_changes) return null;
    return reportData.detailed_changes.find((c) => c.name === resourceParam) ?? null;
  }, [activeDetail, resourceParam, reportData?.detailed_changes]);

  const effectiveActiveFile =
    activeFile || (fileNames.length > 0 ? fileNames[0] : "");

  useEffect(() => {
    if (fileNames.length > 0 && !activeFile) {
      setActiveFile(fileNames[0]);
    }
  }, [content]);

  if (loading) {
    return <Typography variant="subtitle2" component="div" className={styles.loading}>Loading artifact...</Typography>;
  }

  if (content === null) {
    return <Typography variant="subtitle2" component="div" className={styles.loading}>Failed to load artifact</Typography>;
  }

  if (isReport && reportData) {
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
        {reportData.summary && <PlanSummaryBar summary={reportData.summary} />}
        {reportData.potential_impact && (
          <div
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

  if (isGeneratedCode && fileNames.length > 0) {
    return (
      <CodeBlock
        files={files ?? undefined}
        activeFile={effectiveActiveFile}
        onFileChange={setActiveFile}
        showLineNumbers
        height="calc(100vh - 200px)"
      />
    );
  }

  return (
    <CodeBlock
      code={content}
      language={getLanguage(operation.artifact_type, operation.content_type)}
      showLineNumbers
      height="calc(100vh - 200px)"
    />
  );
}
