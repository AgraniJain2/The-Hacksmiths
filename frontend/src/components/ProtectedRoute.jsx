import { Navigate, Outlet } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import Spinner from "./Spinner";
import styles from "./ProtectedRoute.module.css";

/**
 * Gate for any route under it: unauthenticated -> /login, still checking ->
 * a full-page spinner, error reaching the backend -> a friendly message
 * (not a silent redirect loop). Authenticated renders the nested route.
 *
 * Role-gating a specific page: check `user.role` inside that page itself
 * (same pattern the backend uses, see CONVENTIONS.md's RBAC section) —
 * this component only answers "is anyone logged in at all".
 */
export default function ProtectedRoute() {
  const { status, error, refetch } = useAuth();

  if (status === "loading") {
    return (
      <div className={styles.center}>
        <Spinner label="Checking your session…" />
      </div>
    );
  }

  if (status === "error") {
    return (
      <div className={styles.center}>
        <div className={`glass-card ${styles.errorCard}`}>
          <p className={styles.errorText}>
            Couldn't reach WorkHire's backend{error?.message ? ` (${error.message})` : ""}. Is it running?
          </p>
          <button className="btn btn-outline" onClick={refetch}>
            Retry
          </button>
        </div>
      </div>
    );
  }

  if (status === "unauthenticated") {
    return <Navigate to="/login" replace />;
  }

  return <Outlet />;
}
