// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { useCallback, useRef, useEffect, useState } from "react";
import * as monaco from "monaco-editor";
import Editor, { DiffEditor, loader } from "@monaco-editor/react";
import type {
  OnChange,
  OnMount,
  BeforeMount,
  DiffOnMount,
} from "@monaco-editor/react";
import type { editor } from "monaco-editor";
import editorWorker from "monaco-editor/editor/editor.worker?worker";
import jsonWorker from "monaco-editor/language/json/json.worker?worker";
import ThumbUpAltOutlined from "@mui/icons-material/ThumbUpAltOutlined";
import ThumbDownAltOutlined from "@mui/icons-material/ThumbDownAltOutlined";
import { useShell } from "@/contexts/ShellContext";
import { registerHclLanguage } from "@/utils/hclTokenizer";
import { parseGitDiff } from "@/utils/diffUtils";
import { STORAGE_KEYS, THEME } from "@/constants";
import { getLocalItem } from "@/services";
import EditorSkeleton from "../EditorSkeleton";
import styles from "./MonacoEditor.module.css";

// jsdom (tests) has no matchMedia, hence the function check.
const narrowViewport =
  typeof window !== "undefined" &&
  typeof window.matchMedia === "function" &&
  window.matchMedia("(max-width: 768px)").matches;

let monacoConfigured = false;

function ensureMonacoConfigured() {
  if (monacoConfigured) return;
  (self as unknown as { MonacoEnvironment: unknown }).MonacoEnvironment = {
    getWorker(_: unknown, label: string) {
      if (label === "json") return new jsonWorker();
      return new editorWorker();
    },
  };
  loader.config({ monaco });
  // Monaco cancels in-flight work (e.g. a diff computation) when an
  // editor is disposed mid-switch; the cancellation surfaces as an
  // unhandled "Canceled" rejection. Swallow only that one.
  window.addEventListener("unhandledrejection", (e) => {
    if ((e.reason as { name?: string } | null)?.name === "Canceled") {
      e.preventDefault();
    }
  });
  monacoConfigured = true;
}

let themesRegistered = false;

function defineCustomThemes(monacoInstance: typeof monaco): void {
  if (themesRegistered) return;

  monacoInstance.editor.defineTheme("kumoss-light", {
    base: "vs",
    inherit: true,
    rules: [],
    colors: {
      "editor.background": "#00000000",
      "editorLineNumber.foreground": "#00000040",
      "editorLineNumber.activeForeground": "#00000080",
    },
  });

  monacoInstance.editor.defineTheme("kumoss-dark", {
    base: "vs-dark",
    inherit: true,
    rules: [],
    colors: {
      "editor.background": "#00000000",
      "editorLineNumber.foreground": "#ffffff40",
      "editorLineNumber.activeForeground": "#ffffff80",
      // vs-dark's olive/maroon diff tints turn muddy over the app's
      // deep-blue dark background; use brighter green/red instead. Char
      // boxes are disabled: the backend emits full-context diffs where
      // most tokens differ, so per-token boxes read as a solid wall.
      "diffEditor.insertedLineBackground": "#3fb95026",
      "diffEditor.removedLineBackground": "#f8514926",
      "diffEditor.insertedTextBackground": "#00000000",
      "diffEditor.removedTextBackground": "#00000000",
      "diffEditorGutter.insertedLineBackground": "#3fb95038",
      "diffEditorGutter.removedLineBackground": "#f8514938",
      "diffEditor.diagonalFill": "#ffffff14",
      "diffEditor.unchangedRegionBackground": "#ffffff0d",
    },
  });

  themesRegistered = true;
}

const LANGUAGE_MAP: Record<string, string> = {
  hcl: "hcl",
  terraform: "hcl",
  tf: "hcl",
  text: "plaintext",
  json: "json",
  yaml: "yaml",
  yml: "yaml",
  javascript: "javascript",
  typescript: "typescript",
  python: "python",
  bash: "shell",
  sh: "shell",
};

const EXTENSION_MAP: Record<string, string> = {
  tf: "hcl",
  hcl: "hcl",
  tfvars: "hcl",
  js: "javascript",
  jsx: "javascript",
  ts: "typescript",
  tsx: "typescript",
  py: "python",
  json: "json",
  yaml: "yaml",
  yml: "yaml",
  sh: "bash",
  bash: "bash",
  md: "markdown",
  txt: "text",
};

const getMonacoLanguage = (lang: string): string =>
  LANGUAGE_MAP[lang] || "plaintext";

const getLanguageFromFileName = (fileName: string): string => {
  if (!fileName) return "hcl";
  const ext = fileName.split(".").pop()?.toLowerCase();
  return ext ? EXTENSION_MAP[ext] || "hcl" : "hcl";
};

interface MonacoEditorProps {
  code?: string;
  language?: string;
  height?: string;
  readOnly?: boolean;
  showLineNumbers?: boolean;
  onChange?: OnChange;
  options?: editor.IStandaloneEditorConstructionOptions;
  files?: Record<string, string> | null;
  /** Names in `files` holding raw content rather than `git diff` output. */
  newFiles?: ReadonlySet<string> | null;
  activeFile?: string | null;
  onFileChange?: ((fileName: string) => void) | null;
  stickyScroll?: boolean;
  onThumbUp?: () => void;
  onThumbDown?: () => void;
}

const MonacoEditor = ({
  code,
  language = "hcl",
  height = "400px",
  readOnly = true,
  showLineNumbers = true,
  onChange,
  options = {},
  files = null,
  newFiles = null,
  activeFile = null,
  onFileChange = null,
  stickyScroll = false,
  onThumbUp,
  onThumbDown,
}: MonacoEditorProps) => {
  ensureMonacoConfigured();

  const editorRef = useRef<editor.IStandaloneCodeEditor | null>(null);
  const diffEditorRef = useRef<editor.IStandaloneDiffEditor | null>(null);
  const [diffEditorMounts, setDiffEditorMounts] = useState(0);
  const monacoRef = useRef<typeof monaco | null>(null);
  const { isDark } = useShell();

  const [editorTheme, setEditorTheme] = useState(() => {
    const saved = getLocalItem(STORAGE_KEYS.THEME);
    return saved === THEME.DARK;
  });

  useEffect(() => {
    if (typeof isDark === "boolean" && isDark !== editorTheme) {
      setEditorTheme(isDark);
    }
  }, [isDark, editorTheme]);

  const handleBeforeMount: BeforeMount = (monacoInstance) => {
    defineCustomThemes(monacoInstance);
  };

  const fileNames = files ? Object.keys(files) : [];
  const showTabs = files && fileNames.length > 1;

  // Updated-file artifacts hold `git diff` output; new files hold raw
  // content. Which is which is object metadata the backend wrote
  // (`new_file`), carried down as `newFiles` — so the shape is the input
  // here and the diff is derived from it, not the other way round. Diffs
  // render in the diff editor; new files render whole-line "added"
  // decorations, because a diff against an empty original would show a
  // spurious deleted-line marker.
  const activeContent = files && activeFile ? files[activeFile] : undefined;
  const activeIsNewFile =
    activeContent !== undefined &&
    activeFile !== null &&
    (newFiles?.has(activeFile) ?? false);
  const activeDiff =
    activeContent !== undefined && !activeIsNewFile
      ? parseGitDiff(activeContent)
      : null;
  const diffOriginal = activeDiff?.original;
  const diffModified = activeDiff?.modified;
  const activeLanguage = getMonacoLanguage(
    getLanguageFromFileName(activeFile ?? ""),
  );

  // Whole-line "added" tint for new-file artifacts in files mode: they
  // have no diff, so the viewer marks the entire file as added instead.
  const addedDecorations = useRef<editor.IEditorDecorationsCollection | null>(
    null,
  );
  const decorateAsNewFile = useCallback(
    (editorInstance: editor.IStandaloneCodeEditor, isNewFile: boolean) => {
      addedDecorations.current?.clear();
      addedDecorations.current = null;
      const model = editorInstance.getModel();
      if (!isNewFile || !model) return;
      addedDecorations.current = editorInstance.createDecorationsCollection([
        {
          range: model.getFullModelRange(),
          options: {
            isWholeLine: true,
            className: "newFileLineInsert",
            linesDecorationsClassName: "newFileLineInsertMargin",
          },
        },
      ]);
    },
    [],
  );

  // Re-apply after the editor swaps models on tab change (the Editor
  // child's own effects run first, so the new model is already active).
  useEffect(() => {
    if (files && editorRef.current) {
      decorateAsNewFile(editorRef.current, activeIsNewFile);
    }
  }, [files, activeFile, activeIsNewFile, decorateAsNewFile]);

  const handleEditorDidMount: OnMount = (editorInstance, monaco) => {
    defineCustomThemes(monaco);
    editorRef.current = editorInstance;
    monacoRef.current = monaco;
    registerHclLanguage(monaco);
    if (files) decorateAsNewFile(editorInstance, activeIsNewFile);
  };

  useEffect(() => {
    const model = diffEditorRef.current?.getModel();
    if (!model || diffOriginal === undefined || diffModified === undefined) {
      return;
    }
    if (model.original.getValue() !== diffOriginal) {
      model.original.setValue(diffOriginal);
    }
    if (model.modified.getValue() !== diffModified) {
      model.modified.setValue(diffModified);
    }
  }, [diffOriginal, diffModified, diffEditorMounts]);

  const handleDiffEditorDidMount: DiffOnMount = (editorInstance, monaco) => {
    defineCustomThemes(monaco);
    monacoRef.current = monaco;
    registerHclLanguage(monaco);
    diffEditorRef.current = editorInstance;
    setDiffEditorMounts((mounts) => mounts + 1);
  };

  const handleTabClick = (fileName: string) => {
    if (onFileChange) onFileChange(fileName);
  };

  const defaultOptions: editor.IStandaloneEditorConstructionOptions = {
    readOnly,
    minimap: { enabled: false },
    stickyScroll: { enabled: stickyScroll },
    scrollBeyondLastLine: false,
    fontSize: 14,
    fontFamily: "'Monaco', 'Menlo', 'Ubuntu Mono', monospace",
    lineHeight: 21,
    lineNumbers: showLineNumbers ? ("on" as const) : ("off" as const),
    folding: true,
    // Phones: unwrapped code means constant horizontal panning.
    wordWrap: narrowViewport ? ("on" as const) : ("off" as const),
    automaticLayout: true,
    contextmenu: false,
    selectOnLineNumbers: true,
    roundedSelection: false,
    cursorStyle: "line" as const,
    scrollbar: {
      horizontal: "visible" as const,
      vertical: "visible" as const,
      horizontalScrollbarSize: 12,
      verticalScrollbarSize: 12,
    },
    overviewRulerBorder: false,
    hideCursorInOverviewRuler: true,
    ...options,
  };

  // Inline (unified) diff; unchanged regions collapse so the full-context
  // diffs the backend produces read like plain `git diff` output.
  const diffOptions: editor.IDiffEditorConstructionOptions = {
    ...defaultOptions,
    renderSideBySide: false,
    hideUnchangedRegions: { enabled: true },
    renderOverviewRuler: false,
  };

  const monacoTheme = editorTheme ? "kumoss-dark" : "kumoss-light";

  const containerStyle = { height };
  const editorWrapperStyle = showTabs
    ? { height: `calc(${height} - 28px)` }
    : { height };

  return (
    <div className={styles.container} style={containerStyle}>
      {showTabs && (
        <div className={styles.tabBar}>
          {fileNames.map((fileName) => (
            <button
              key={fileName}
              className={`${styles.tab} ${activeFile === fileName ? styles.tabActive : ""}`}
              onClick={() => handleTabClick(fileName)}
            >
              {fileName}
            </button>
          ))}
        </div>
      )}
      <div className={styles.editorWrapper} style={editorWrapperStyle}>
        {files ? (
          activeDiff ? (
            <DiffEditor
              loading={<EditorSkeleton height={height} />}
              height={height}
              language={activeLanguage}
              original={activeDiff.original}
              modified={activeDiff.modified}
              originalModelPath={`diff-original:///${activeFile ?? "file"}`}
              modifiedModelPath={`diff-modified:///${activeFile ?? "file"}`}
              // Keep models across unmounts: the library disposes them
              // before resetting the widget, which throws mid-teardown.
              keepCurrentOriginalModel
              keepCurrentModifiedModel
              theme={monacoTheme}
              beforeMount={handleBeforeMount}
              onMount={handleDiffEditorDidMount}
              options={diffOptions}
            />
          ) : (
            <Editor
              loading={<EditorSkeleton height={height} />}
              height={height}
              path={activeFile ?? undefined}
              language={activeLanguage}
              value={activeContent ?? ""}
              theme={monacoTheme}
              beforeMount={handleBeforeMount}
              onMount={handleEditorDidMount}
              onChange={onChange}
              options={defaultOptions}
            />
          )
        ) : (
          <Editor
            loading={<EditorSkeleton height={height} />}
            height={height}
            language={getMonacoLanguage(language)}
            value={code || ""}
            theme={monacoTheme}
            beforeMount={handleBeforeMount}
            onMount={handleEditorDidMount}
            onChange={onChange}
            options={defaultOptions}
          />
        )}
      </div>
      {(onThumbUp || onThumbDown) && (
        <div className={styles.actionBar}>
          {onThumbUp && (
            <button
              className={styles.actionIcon}
              onClick={onThumbUp}
              aria-label="Like this code"
              type="button"
            >
              <ThumbUpAltOutlined sx={{ fontSize: 20 }} />
            </button>
          )}
          {onThumbDown && (
            <button
              className={styles.actionIcon}
              onClick={onThumbDown}
              aria-label="Dislike this code"
              type="button"
            >
              <ThumbDownAltOutlined sx={{ fontSize: 20 }} />
            </button>
          )}
        </div>
      )}
    </div>
  );
};

export default MonacoEditor;
