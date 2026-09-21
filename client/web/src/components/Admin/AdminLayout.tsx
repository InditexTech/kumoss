// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { useState } from "react";
import { Navigate } from "react-router-dom";
import { ButtonBase } from "@mui/material";
import { useAuth } from "@/contexts/AuthContext";
import SessionsPage from "@/components/Sessions/SessionsPage";
import UsersPanel from "./UsersPanel";
import styles from "./AdminLayout.module.css";

type AdminTab = "sessions" | "users";

function AdminLayout() {
  const { hasPanelAccess, isPanelAdmin } = useAuth();
  const [tab, setTab] = useState<AdminTab>("sessions");

  if (!hasPanelAccess) return <Navigate to="/" replace />;

  const activeTab = tab === "users" && !isPanelAdmin ? "sessions" : tab;

  return (
    <div className={styles.container}>
      <div className={styles.tabs}>
        <ButtonBase
          className={
            activeTab === "sessions"
              ? `${styles.tab} ${styles.tabActive}`
              : styles.tab
          }
          onClick={() => setTab("sessions")}
        >
          Sessions
        </ButtonBase>
        {isPanelAdmin && (
          <ButtonBase
            className={
              activeTab === "users"
                ? `${styles.tab} ${styles.tabActive}`
                : styles.tab
            }
            onClick={() => setTab("users")}
          >
            Users
          </ButtonBase>
        )}
      </div>
      <main className={styles.content}>
        {activeTab === "sessions" ? (
          <SessionsPage variant="admin" />
        ) : (
          <UsersPanel />
        )}
      </main>
    </div>
  );
}

export default AdminLayout;
