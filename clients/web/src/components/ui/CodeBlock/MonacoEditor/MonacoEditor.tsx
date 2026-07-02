import { useRef, useEffect, useState } from "react";
import * as monaco from "monaco-editor";
import Editor, { loader } from "@monaco-editor/react";
import type { OnChange, OnMount, BeforeMount } from "@monaco-editor/react";
import type { editor } from "monaco-editor";
import editorWorker from "monaco-editor/esm/vs/editor/editor.worker?worker";
import jsonWorker from "monaco-editor/esm/vs/language/json/json.worker?worker";
import ThumbUpAltOutlined from "@mui/icons-material/ThumbUpAltOutlined";
import ThumbDownAltOutlined from "@mui/icons-material/ThumbDownAltOutlined";
import { useShell } from "@/contexts/ShellContext";
import { registerHclLanguage } from "@/utils/hclTokenizer";
import { STORAGE_KEYS, THEME } from "@/constants";
import { getLocalItem } from "@/services";
import EditorSkeleton from "../EditorSkeleton";
import styles from "./MonacoEditor.module.css";

let monacoConfigured = false;

function ensureMonacoConfigured() {
  if (monacoConfigured) return;
  self.MonacoEnvironment = {
    getWorker(_, label) {
      if (label === "json") return new jsonWorker();
      return new editorWorker();
    },
  };
  loader.config({ monaco });
  monacoConfigured = true;
}

let themesRegistered = false;

function defineCustomThemes(monacoInstance: typeof monaco): void {
  if (themesRegistered) return;

  monacoInstance.editor.defineTheme("nebula-light", {
    base: "vs",
    inherit: true,
    rules: [],
    colors: {
      "editor.background": "#00000000",
      "editorLineNumber.foreground": "#00000040",
      "editorLineNumber.activeForeground": "#00000080",
    },
  });

  monacoInstance.editor.defineTheme("nebula-dark", {
    base: "vs-dark",
    inherit: true,
    rules: [],
    colors: {
      "editor.background": "#00000000",
      "editorLineNumber.foreground": "#ffffff40",
      "editorLineNumber.activeForeground": "#ffffff80",
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
  activeFile = null,
  onFileChange = null,
  stickyScroll = false,
  onThumbUp,
  onThumbDown,
}: MonacoEditorProps) => {
  ensureMonacoConfigured();

  const editorRef = useRef<editor.IStandaloneCodeEditor | null>(null);
  const monacoRef = useRef<typeof monaco | null>(null);
  const { isDark } = useShell();

  const [editorTheme, setEditorTheme] = useState(() => {
    const saved = getLocalItem(STORAGE_KEYS.THEME);
    return saved === THEME.DARK || !saved;
  });

  useEffect(() => {
    if (typeof isDark === "boolean" && isDark !== editorTheme) {
      setEditorTheme(isDark);
    }
  }, [isDark, editorTheme]);

  const handleBeforeMount: BeforeMount = (monacoInstance) => {
    defineCustomThemes(monacoInstance);
  };

  const handleEditorDidMount: OnMount = (editorInstance, monaco) => {
    defineCustomThemes(monaco);
    editorRef.current = editorInstance;
    monacoRef.current = monaco;

    if (files && Object.keys(files).length > 0) {
      Object.entries(files).forEach(([fileName, fileContent]) => {
        const uri = monaco.Uri.parse(`file:///${fileName}`);
        const existingModel = monaco.editor.getModel(uri);
        if (existingModel) existingModel.dispose();

        const model = monaco.editor.createModel(
          fileContent,
          getMonacoLanguage(getLanguageFromFileName(fileName)),
          uri,
        );

        if (fileName === activeFile) {
          editorInstance.setModel(model);
        }
      });
    }

    registerHclLanguage(monaco);
  };

  useEffect(() => {
    if (monacoRef.current && editorRef.current && files && activeFile) {
      const uri = monacoRef.current.Uri.parse(`file:///${activeFile}`);
      const model = monacoRef.current.editor.getModel(uri);
      if (model) editorRef.current.setModel(model);
    }
  }, [activeFile, files]);

  const handleTabClick = (fileName: string) => {
    if (onFileChange) onFileChange(fileName);
  };

  const fileNames = files ? Object.keys(files) : [];
  const showTabs = files && fileNames.length > 1;

  const defaultOptions: editor.IStandaloneEditorConstructionOptions = {
    readOnly,
    minimap: { enabled: false },
    stickyScroll: { enabled: stickyScroll },
    scrollBeyondLastLine: false,
    fontSize: 17,
    fontFamily: "'Monaco', 'Menlo', 'Ubuntu Mono', monospace",
    lineHeight: 27,
    lineNumbers: showLineNumbers ? ("on" as const) : ("off" as const),
    folding: true,
    wordWrap: "off" as const,
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

  const monacoTheme = editorTheme ? "nebula-dark" : "nebula-light";

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
          <Editor
            loading={<EditorSkeleton height={height} />}
            height={height}
            theme={monacoTheme}
            beforeMount={handleBeforeMount}
            onMount={handleEditorDidMount}
            onChange={onChange}
            options={defaultOptions}
          />
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
