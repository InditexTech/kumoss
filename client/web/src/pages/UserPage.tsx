// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { useNavigate } from "react-router-dom";
import { ButtonBase, Divider, Typography } from "@mui/material";
import PersonIcon from "@mui/icons-material/Person";
import ArrowForwardIcon from "@mui/icons-material/ArrowForward";
import LogoutIcon from "@mui/icons-material/Logout";
import { useAuth } from "@/contexts/AuthContext";
import styles from "./UserPage.module.css";

export default function UserPage() {
  const navigate = useNavigate();
  const { user, logout, hasPanelAccess } = useAuth();

  const displayName =
    user?.displayName || (user?.email ? user.email.split("@")[0] : "User");
  const email = user?.email || "";

  return (
    <div className={styles.container}>
      <main className={styles.content}>
        <div className={styles.pageHeader}>
          <h1 className={styles.pageTitle}>User</h1>
          <ButtonBase
            className={styles.backButton}
            onClick={() => navigate("/home")}
          >
            <span className={styles.backButtonText}>Return</span>
            <ArrowForwardIcon className={styles.backButtonIcon} />
          </ButtonBase>
        </div>

        <section className={styles.section}>
          <Typography variant="caption" component="h2" className={styles.sectionTitle}>Profile</Typography>
          <div className={styles.userCard}>
            <div className={styles.userCardTop}>
              <div className={styles.userAvatar}>
                <PersonIcon className={styles.avatarIcon} />
              </div>
              <div className={styles.userDetails}>
                <Typography variant="subtitle2" className={styles.userName}>{displayName}</Typography>
                <p className={styles.userEmail}>{email}</p>
              </div>
            </div>
            <div className={styles.userCardBottom}>
              <ButtonBase
                className={styles.logoutButton}
                onClick={() => {
                  void logout();
                }}
              >
                <LogoutIcon className={styles.logoutIcon} />
                <span className={styles.logoutText}>Log out</span>
              </ButtonBase>
            </div>
          </div>
        </section>

        <Divider />

        <section className={styles.section} style={{ marginTop: 40 }}>
          <Typography variant="caption" component="h2" className={styles.sectionTitle}>Session History</Typography>
          <ButtonBase
            className={styles.backButton}
            onClick={() => navigate("/user/sessions")}
          >
            <span className={styles.backButtonText}>View all sessions</span>
            <ArrowForwardIcon className={styles.backButtonIcon} />
          </ButtonBase>
        </section>

        {hasPanelAccess && (
          <>
            <Divider />

            <section className={styles.section} style={{ marginTop: 40 }}>
              <Typography variant="caption" component="h2" className={styles.sectionTitle}>Admin</Typography>
              <ButtonBase
                className={styles.backButton}
                onClick={() => navigate("/admin")}
              >
                <span className={styles.backButtonText}>Admin Panel</span>
                <ArrowForwardIcon className={styles.backButtonIcon} />
              </ButtonBase>
            </section>
          </>
        )}

      </main>
    </div>
  );
}
