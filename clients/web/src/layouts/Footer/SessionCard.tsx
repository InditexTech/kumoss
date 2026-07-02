import { useNavigate } from "react-router-dom";
import Typography from "@mui/material/Typography";
import type { UserSessionInfo } from "@/types/api";
import styles from "./SessionCard.module.css";

interface SessionCardProps {
  session: UserSessionInfo;
  onClick?: (session: UserSessionInfo) => void;
}

function formatDate(dateStr: string): string {
  const d = new Date(dateStr);
  const day = String(d.getDate()).padStart(2, "0");
  const month = String(d.getMonth() + 1).padStart(2, "0");
  return `${day}.${month}.${d.getFullYear()}`;
}

function extractProjectName(repoUri: string): string {
  const segments = repoUri.replace(/\/+$/, "").split("/");
  return segments[segments.length - 1] || repoUri;
}

export default function SessionCard({ session, onClick }: SessionCardProps) {
  const navigate = useNavigate();

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
        <button
          className={styles.menuButton}
          onClick={(e) => {
            e.stopPropagation();
            navigate(`/user/sessions?session=${session.session_id}`);
          }}
        >
          &middot;&middot;&middot;
        </button>
      </div>
      <div className={styles.cardContent}>
        {session.initial_query && (
          <Typography variant="body2" component="p" className={styles.query}>
            {session.initial_query}
          </Typography>
        )}
        <div className={styles.divider} />
        <Typography variant="h4" component="div" className={styles.projectName}>
          {extractProjectName(session.repo_uri)}
        </Typography>
      </div>
    </div>
  );
}
