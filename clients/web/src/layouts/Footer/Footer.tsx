import { useLocation } from "react-router-dom";
import { useSession } from "@/contexts/SessionContext";
import { useCurrentView } from "@/hooks/useCurrentView";
import { Slide } from "@mui/material";
import Typography from "@mui/material/Typography";
import UserSessionsHistory from "./UserSessionsHistory";
import styles from "./Footer.module.css";

const Footer = () => {
  const { pathname } = useLocation();
  const { session } = useSession();
  const view = useCurrentView();

  if (!pathname.startsWith("/home")) return null;

  const isTimelineMode = view === null || view === "wizard";

  const truncateMsg = (msg: string) => {
    return msg.length > 40 ? `${msg.slice(0, 40)}...` : msg;
  };

  const hasContent =
    !!session.firstQuery ||
    !!session.cloud ||
    !!session.project ||
    !!session.environment;

  if (isTimelineMode) {
    return (
      <div className={styles.timelineContainer}>
        <UserSessionsHistory pageSize={20} />
      </div>
    );
  }

  return (
    <Slide direction="up" in={hasContent} timeout={500} mountOnEnter unmountOnExit>
      <div className={styles.footerContainer}>
        {session.firstQuery && (
          <div className={styles.containerUnit}>
            <Typography variant="h3">Query</Typography>
            <span>/</span>
            <Typography variant="h3" className={styles.mainMsg} title={session.firstQuery}>
              {truncateMsg(session.firstQuery)}
            </Typography>
          </div>
        )}
        {session.cloud && (
          <div className={styles.containerUnit}>
            <Typography variant="h3">Cloud</Typography>
            <span>/</span>
            <Typography variant="h3" className={styles.mainMsg} title={session.cloud}>
              {truncateMsg(session.cloud)}
            </Typography>
          </div>
        )}
        {session.project && (
          <div className={styles.containerUnit}>
            <Typography variant="h3">Project</Typography>
            <span>/</span>
            <Typography variant="h3" className={styles.mainMsg} title={session.project}>
              {truncateMsg(session.project)}
            </Typography>
          </div>
        )}
        {session.environment && (
          <div className={styles.containerUnit}>
            <Typography variant="h3">Environment</Typography>
            <span>/</span>
            <Typography variant="h3" className={styles.mainMsg} title={session.environment}>
              {truncateMsg(session.environment)}
            </Typography>
          </div>
        )}
      </div>
    </Slide>
  );
};

export default Footer;
