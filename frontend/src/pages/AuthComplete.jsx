import { Link, Navigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { homeRouteFor } from "../lib/roles";
import BackgroundFX from "../components/BackgroundFX";
import Spinner from "../components/Spinner";
import { IconAlert } from "../components/icons";
import styles from "./AuthComplete.module.css";

/**
 * Landing page for `FRONTEND_URL/auth/complete`, where the backend's
 * `/auth/google/callback` redirects after setting the session cookie (see
 * AUTH_MODULE.md). AuthProvider already fetches /auth/me on mount — this
 * page just watches that result and routes accordingly, rather than
 * duplicating the request.
 */
export default function AuthComplete() {
  const { status, user, error, refetch } = useAuth();

  if (status === "authenticated") {
    return <Navigate to={homeRouteFor(user.role)} replace />;
  }

  return (
    <div className={styles.page}>
      <BackgroundFX />
      <div className={`glass-card ${styles.card} animate-in`}>
        {status === "unauthenticated" && (
          <>
            <IconAlert width={28} height={28} className={styles.errorIcon} />
            <h1 className={`heading-display ${styles.heading}`}>Sign-in didn't go through</h1>
            <p className={styles.subtitle}>
              No session was found. This can happen if the invite link expired or your account isn't
              registered yet — ask your recruiter, or try again.
            </p>
            <Link to="/login" className="btn btn-primary">
              Back to sign in
            </Link>
          </>
        )}
        {status === "error" && (
          <>
            <IconAlert width={28} height={28} className={styles.errorIcon} />
            <h1 className={`heading-display ${styles.heading}`}>Couldn't confirm your session</h1>
            <p className={styles.subtitle}>{error?.message || "The backend didn't respond."}</p>
            <button className="btn btn-primary" onClick={refetch}>
              Retry
            </button>
          </>
        )}
        {status === "loading" && (
          <>
            <Spinner size={28} />
            <h1 className={`heading-display ${styles.heading}`}>Finishing sign-in…</h1>
            <p className={styles.subtitle}>Confirming your session with WorkHire.</p>
          </>
        )}
      </div>
    </div>
  );
}
