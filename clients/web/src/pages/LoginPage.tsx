import { useState } from "react";
import type { FormEvent } from "react";
import { ButtonBase, TextField } from "@mui/material";
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
  const { login } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (email.trim() && password.trim()) {
      login(email.trim(), password.trim());
    }
  };

  return (
    <div className={styles.loginContainer}>
      <div className={styles.loginContent}>
        <Fade in timeout={800}>
          <form className={styles.form} onSubmit={handleSubmit}>
            <TextField
              className={styles.field}
              label={STRINGS.login.emailLabel}
              type="email"
              variant="standard"
              required
              autoFocus
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
            <TextField
              className={styles.field}
              label={STRINGS.login.passwordLabel}
              type="password"
              variant="standard"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
            <ButtonBase
              className={styles.submitButton}
              type="submit"
              component="button"
            >
              {STRINGS.login.signIn}
            </ButtonBase>
          </form>
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
