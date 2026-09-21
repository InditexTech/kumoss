// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { extractProjectName } from "@/utils/workspace";
import { formatDate } from "@/utils/datetime";
import Typography from "@mui/material/Typography";
import type { SessionSummary } from "@/types/api";
import styles from "./SessionCard.module.css";

interface SessionCardProps {
  session: SessionSummary;
  onClick?: (session: SessionSummary) => void;
}

export default function SessionCard({ session, onClick }: SessionCardProps) {
  return (
    <div className={styles.card} onClick={() => onClick?.(session)}>
      <div className={styles.cardHeader}>
        <Typography
          variant="subtitle2"
          component="span"
          className={styles.date}
        >
          {formatDate(session.created_at)}
        </Typography>
      </div>
      <div className={styles.cardContent}>
        {session.first_query && (
          <Typography variant="body2" component="p" className={styles.query}>
            {session.first_query}
          </Typography>
        )}
        <div className={styles.divider} />
        <Typography variant="h4" component="div" className={styles.projectName}>
          {extractProjectName(session.workspace_uri)}
        </Typography>
      </div>
    </div>
  );
}
