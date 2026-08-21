// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import styles from "./MarkdownText.module.css";

interface MarkdownTextProps {
  content: string;
  className?: string;
}

/** Renders markdown body text (GFM). Raw HTML in the source is skipped. */
export default function MarkdownText({ content, className }: MarkdownTextProps) {
  return (
    <div className={`${styles.markdown}${className ? ` ${className}` : ""}`}>
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
    </div>
  );
}
