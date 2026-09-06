import { Navigate, useSearchParams } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { homeRouteFor } from "../lib/roles";
import { api } from "../lib/api";
import BackgroundFX from "../components/BackgroundFX";
import Logo from "../components/Logo";
import { IconGoogle, IconSparkle } from "../components/icons";
import styles from "./Login.module.css";

export default function Login() {
  const { status, user } = useAuth();
  const [params] = useSearchParams();
  const inviteToken = params.get("invite_token");

  // Nothing to do if we already have a session — send straight through.
  if (status === "authenticated") {
    return <Navigate to={homeRouteFor(user.role)} replace />;
  }

  return (
    <div className={styles.page}>
      <BackgroundFX />
      <div className={`glass-card ${styles.card} animate-in`}>
        <div className={styles.brandRow}>
          <Logo size="lg" />
        </div>

        {inviteToken ? (
          <>
            <p className={styles.inviteNotice}>
              <IconSparkle width={14} height={14} />
              You've been invited to an interview
            </p>
            <h1 className={`heading-display ${styles.heading}`}>Confirm it's you</h1>
            <p className={styles.subtitle}>
              Sign in with the Google account this invite was sent to — that's how we match you to the
              interview.
            </p>
          </>
        ) : (
          <>
            <h1 className={`heading-display ${styles.heading}`}>Welcome to WorkHire</h1>
            <p className={styles.subtitle}>Sign in with your Google account to continue.</p>
          </>
        )}

        <a href={api.googleLoginUrl(inviteToken)} className={`btn ${styles.googleBtn}`}>
          <IconGoogle />
          Continue with Google
        </a>

        <p className={styles.footnote}>
          Staff sign in with the Google account listed for their role. Candidates use the link from their
          interview invite email — signing in without one won't create an account.
        </p>
      </div>
    </div>
  );
}
