// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { useLocation, useNavigate } from "react-router-dom";
import { useSession } from "@/contexts/SessionContext";
import { useCurrentView } from "@/hooks/useCurrentView";
import { Slide, Tooltip } from "@mui/material";
import Typography from "@mui/material/Typography";
import { ProviderIcon } from "@/components/ui";
import { extractProjectName } from "@/utils/workspace";
import UserSessionsHistory from "./UserSessionsHistory";
import styles from "./Footer.module.css";

const Footer = () => {
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const { session } = useSession();
  const view = useCurrentView();

  if (!pathname.startsWith("/home")) return null;

  const isTimelineMode = view === null || view === "wizard";

  const repoUri = session.workspace?.uri;
  const rootPath = session.workspace?.root_path;

  const hasContent =
    !!session.first_query || !!session.provider || !!repoUri || !!rootPath;

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
        {session.first_query && (
          <div className={styles.containerUnitLarge}>
            <Typography variant="h3">Query</Typography>
            <span>/</span>
            <Tooltip title={session.first_query} arrow>
              <Typography variant="h3" className={styles.mainMsg}>
                {session.first_query}
              </Typography>
            </Tooltip>
          </div>
        )}
        {repoUri && (
          <div className={styles.containerUnit}>
            <Typography variant="h3">Project</Typography>
            <span>/</span>
            <Tooltip title={repoUri} arrow>
              <Typography variant="h3" className={styles.mainMsg}>
                {extractProjectName(repoUri)}
              </Typography>
            </Tooltip>
          </div>
        )}
        {rootPath && (
          <div className={styles.containerUnitSmall}>
            <Typography variant="h3">Path</Typography>
            <span>/</span>
            <Tooltip title={rootPath} arrow>
              <Typography variant="h3" className={styles.mainMsg}>
                {rootPath}
              </Typography>
            </Tooltip>
          </div>
        )}
        {session.provider && (
          <div className={styles.containerUnitIcon}>
            <Tooltip title={session.provider} arrow>
              <ProviderIcon
                provider={session.provider}
                className={styles.providerBadge}
                aria-label={session.provider}
              />
            </Tooltip>
          </div>
        )}
      </div>
    </Slide>
  );
};

export default Footer;
