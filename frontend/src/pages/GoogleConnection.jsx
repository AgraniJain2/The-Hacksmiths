import GoogleConnectionCard from "../components/GoogleConnectionCard";
import styles from "./GoogleConnection.module.css";

export default function GoogleConnection() {
  return (
    <div className={`animate-in ${styles.wrap}`}>
      <div className={styles.header}>
        <h1 className={`heading-display ${styles.heading}`}>Google connection</h1>
        <p className={styles.subtitle}>
          WorkHire's sign-in is Google itself, so Calendar access (to check availability and create
          events) and Gmail access (to send notifications on your behalf) are granted the moment you
          log in — there's nothing separate to connect here.
        </p>
      </div>

      <GoogleConnectionCard variant="full" />

      <div className={`glass-card ${styles.noteCard}`}>
        <p className={styles.noteTitle}>Good to know</p>
        <ul className={styles.noteList}>
          <li>Google tokens never leave the backend — WorkHire never asks for them directly.</li>
          <li>If this ever shows "Not connected," sign out and back in with Google to re-link it.</li>
        </ul>
      </div>
    </div>
  );
}
