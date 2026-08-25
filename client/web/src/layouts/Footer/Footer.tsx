// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { useLocation, useNavigate } from "react-router-dom";
import { useSession } from "@/contexts/SessionContext";
import { useCurrentView } from "@/hooks/useCurrentView";
import { Slide, Tooltip } from "@mui/material";
import Typography from "@mui/material/Typography";
import { ProviderIcon } from "@/components/ui";
import UserSessionsHistory from "./UserSessionsHistory";
import styles from "./Footer.module.css";

const Footer = () => {
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const { session } = useSession();
  const view = useCurrentView();

  if (!pathname.startsWith("/home")) return null;

  const isTimelineMode = view === null || view === "wizard";

  const extractProjectName = (url: string) => {
    return url.split("/").pop() || url;
  };

  const hasContent =
    !!session.firstQuery ||
    !!session.cloud ||
    !!session.project ||
    !!session.environment;

  if (isTimelineMode) {
    return (
      <div className={styles.timelineContainer}>
        <UserSessionsHistory
          pageSize={20}
          onSelectSession={(s) => navigate(`/user/sessions?session=${s.uuid}`)}
        />
      </div>
    );
  }

  return (
    <Slide
      direction="up"
      in={hasContent}
      timeout={500}
      mountOnEnter
      unmountOnExit
    >
      <div className={styles.footerContainer}>
        {session.firstQuery && (
          <div className={styles.containerUnitLarge}>
            <Typography variant="h3">Query</Typography>
            <span>/</span>
            <Tooltip title={session.firstQuery} arrow>
              <Typography variant="h3" className={styles.mainMsg}>
                {session.firstQuery}
              </Typography>
            </Tooltip>
          </div>
        )}
        {session.project && (
          <div className={styles.containerUnit}>
            <Typography variant="h3">Project</Typography>
            <span>/</span>
            <Tooltip title={session.project} arrow>
              <Typography variant="h3" className={styles.mainMsg}>
                {extractProjectName(session.project)}
              </Typography>
            </Tooltip>
          </div>
        )}
        {session.environment && (
          <div className={styles.containerUnitSmall}>
            <Typography variant="h3">Path</Typography>
            <span>/</span>
            <Tooltip title={session.environment} arrow>
              <Typography variant="h3" className={styles.mainMsg}>
                {session.environment}
              </Typography>
            </Tooltip>
          </div>
        )}
        {session.cloud && (
          <div className={styles.containerUnitIcon}>
            <Tooltip title={session.cloud} arrow>
              <ProviderIcon
                provider={session.cloud}
                className={styles.providerBadge}
                aria-label={session.cloud}
              />
            </Tooltip>
          </div>
        )}
      </div>
    </Slide>
  );
};

export default Footer;
