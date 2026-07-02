import React, { lazy, Suspense, useState, useEffect } from 'react';
import ErrorBoundary from '@/components/ui/ErrorBoundary/ErrorBoundary';
import EditorSkeleton from './EditorSkeleton';

const MonacoEditor = lazy(() => import('@/components/ui/CodeBlock/MonacoEditor/MonacoEditor'));

interface Props {
  code?: string;
  files?: Record<string, string>;
  activeFile?: string;
  onFileChange?: (fileName: string) => void;
  language?: string;
  showLineNumbers?: boolean;
  height?: string;
  stickyScroll?: boolean;
  onThumbUp?: () => void;
  onThumbDown?: () => void;
}

const CodeBlock = ({
  code,
  files,
  activeFile,
  onFileChange,
  language = 'hcl',
  showLineNumbers = false,
  height = '400px',
  stickyScroll,
  onThumbUp,
  onThumbDown,
}: Props) => {
  const [internalActiveFile, setInternalActiveFile] = useState(activeFile || '');

  // Always call hooks at the top level
  const fileNames = files ? Object.keys(files) : [];
  const hasFiles = files && fileNames.length > 0;
  const hasSingleCode = code && !files;

  // Initialize active file if not provided - always call useEffect
  useEffect(() => {
    if (hasFiles) {
      if (!activeFile && fileNames.length > 0) {
        const firstFile = fileNames[0];
        setInternalActiveFile(firstFile);
        if (onFileChange) {
          onFileChange(firstFile);
        }
      } else if (activeFile) {
        setInternalActiveFile(activeFile);
      }
    }
  }, [activeFile, fileNames, onFileChange, hasFiles]);

  const handleFileChange = (fileName: string) => {
    setInternalActiveFile(fileName);
    if (onFileChange) {
      onFileChange(fileName);
    }
  };

  // Handle single file mode (backward compatibility)
  if (hasSingleCode) {
    return (
      <ErrorBoundary>
        <Suspense fallback={<EditorSkeleton height={height} />}>
          <MonacoEditor
            code={code}
            language={language}
            showLineNumbers={showLineNumbers}
            height={height}
            readOnly={true}
            stickyScroll={stickyScroll}
            onThumbUp={onThumbUp}
            onThumbDown={onThumbDown}
          />
        </Suspense>
      </ErrorBoundary>
    );
  }

  // Handle multiple files mode with Monaco native tabs
  if (hasFiles) {
    return (
      <ErrorBoundary>
        <Suspense fallback={<EditorSkeleton height={height} />}>
          <MonacoEditor
            files={files}
            activeFile={internalActiveFile || activeFile}
            onFileChange={handleFileChange}
            showLineNumbers={showLineNumbers}
            height={height}
            readOnly={true}
            stickyScroll={stickyScroll}
            onThumbUp={onThumbUp}
            onThumbDown={onThumbDown}
          />
        </Suspense>
      </ErrorBoundary>
    );
  }

  // Fallback for no content
  return (
    <div className="codeBlockEmpty" style={{ height }}>
      <p>No code available to display.</p>
    </div>
  );
};

export default CodeBlock;
