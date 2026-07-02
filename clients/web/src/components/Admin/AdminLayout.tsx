import { Navigate } from "react-router-dom";
import { useAuth } from "@/contexts/AuthContext";
import SessionsPage from "@/components/Sessions/SessionsPage";
import styles from "./AdminLayout.module.css";

function AdminLayout() {
  const { isAdmin } = useAuth();

  if (!isAdmin) return <Navigate to="/" replace />;

  return (
    <div className={styles.container}>
      <h1 className={styles.title}>Sessions</h1>
      <main className={styles.content}>
        <SessionsPage variant="admin" />
      </main>
    </div>
  );
}

export default AdminLayout;
