// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { ButtonBase } from "@mui/material";
import Fade from "@mui/material/Fade";
import BuildOutlinedIcon from "@mui/icons-material/BuildOutlined";
import SearchOutlinedIcon from "@mui/icons-material/SearchOutlined";
import DownloadOutlinedIcon from "@mui/icons-material/DownloadOutlined";
import { useAuth } from "@/contexts/AuthContext";
import { STRINGS } from "@/constants/strings";
import styles from "./LoginPage.module.css";

const USE_CASES = [
  {
    icon: BuildOutlinedIcon,
    title: STRINGS.login.generateTitle,
    description: STRINGS.login.generateDescription,
  },
  {
    icon: SearchOutlinedIcon,
    title: STRINGS.login.detectDriftTitle,
    description: STRINGS.login.detectDriftDescription,
  },
  {
    icon: DownloadOutlinedIcon,
    title: STRINGS.login.importTitle,
    description: STRINGS.login.importDescription,
  },
];

function LoginPage() {
  const { login, sessionExpired, authError } = useAuth();

  return (
    <div className={styles.loginContainer}>
      <div className={styles.loginContent}>
        <Fade in timeout={800}>
          <div className={styles.form}>
            {sessionExpired && (
              <p className={styles.notice}>{STRINGS.login.sessionExpired}</p>
            )}
            {authError && !sessionExpired && (
              <p className={styles.notice}>{authError}</p>
            )}
            <ButtonBase
              className={styles.submitButton}
              component="button"
              onClick={() => {
                void login();
              }}
            >
              {STRINGS.login.signIn}
            </ButtonBase>
          </div>
        </Fade>
      </div>

      <Fade in timeout={1000}>
        <div className={styles.useCasesSection}>
          <div className={styles.useCasesGrid}>
            {USE_CASES.map((useCase) => (
              <div key={useCase.title} className={styles.useCaseCard}>
                <h3 className={styles.useCaseTitle}>{useCase.title}</h3>
                <p className={styles.useCaseDescription}>
                  {useCase.description}
                </p>
                <useCase.icon className={styles.useCaseIcon} />
              </div>
            ))}
          </div>
        </div>
      </Fade>
    </div>
  );
}

export default LoginPage;
