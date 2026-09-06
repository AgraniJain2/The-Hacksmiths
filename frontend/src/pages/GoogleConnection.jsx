import GoogleConnectionCard from "../components/GoogleConnectionCard";
import styles from "./GoogleConnection.module.css";

export default function GoogleConnection() {
  return (
    <div className={`animate-in ${styles.wrap}`}>
      <div className={styles.header}>
        <h1 className={`heading-display ${styles.heading}`}>Google connection</h1>
        <p className={styles.subtitle}>
          WorkHire needs Calendar access to check availability and create events, and Gmail to send
          notifications on your behalf. Disconnecting keeps you logged in but blocks anything that touches
          your calendar or email.
        </p>
      </div>

      <GoogleConnectionCard variant="full" />

      <div className={`glass-card ${styles.noteCard}`}>
        <p className={styles.noteTitle}>Good to know</p>
        <ul className={styles.noteList}>
          <li>Google tokens never leave the backend — WorkHire never asks for them directly.</li>
          <li>Reconnecting re-runs Google's consent screen; it doesn't create a second account.</li>
          <li>If a feature says "reconnect required", it's this page it's pointing you to.</li>
        </ul>
      </div>
    </div>
  );
}
