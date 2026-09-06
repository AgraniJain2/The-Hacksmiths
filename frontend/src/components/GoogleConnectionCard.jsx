import { useAuth } from "../context/AuthContext";
import { IconCalendar, IconGoogle, IconMail } from "./icons";
import ScopeBadge from "./ScopeBadge";
import styles from "./GoogleConnectionCard.module.css";

const SCOPES = [
  { key: "calendar", label: "Calendar", icon: IconCalendar, url: "https://www.googleapis.com/auth/calendar" },
  { key: "gmail", label: "Gmail send", icon: IconMail, url: "https://www.googleapis.com/auth/gmail.send" },
];

/**
 * Google connection status, read-only. WorkHire's only login is Google
 * OAuth itself (offline access, consent screen requests Calendar + Gmail up
 * front — see AUTH_MODULE.md), so every signed-in user is already connected;
 * there's no separate connect/reconnect/disconnect action for people to take
 * here. `variant="summary"` is the compact card used on the dashboard;
 * `variant="full"` (default) is the version used at /settings/google — both
 * read the same AuthContext so they never go out of sync.
 */
export default function GoogleConnectionCard({ variant = "full" }) {
  const { user } = useAuth();

  const connected = Boolean(user?.google_connected);
  const granted = user?.granted_scopes || [];

  return (
    <div className={`glass-card ${styles.card}`}>
      <div className={styles.header}>
        <span className={styles.iconWrap}>
          <IconGoogle />
        </span>
        <div>
          <h3 className={styles.title}>Google connection</h3>
          <p className={styles.subtitle}>
            {connected
              ? "Calendar and email access are linked to this account."
              : "Not connected — sign in with Google again to link it."}
          </p>
        </div>
        <span className={`pill ${connected ? "pill-success" : "pill-warning"} ${styles.statusPill}`}>
          {connected ? "Connected" : "Not connected"}
        </span>
      </div>

      <div className={styles.scopes}>
        {SCOPES.map((s) => (
          <ScopeBadge key={s.key} label={s.label} granted={connected && granted.includes(s.url)} />
        ))}
      </div>
    </div>
  );
}
