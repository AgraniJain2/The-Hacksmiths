import { useState } from "react";
import { api } from "../lib/api";
import { useAuth } from "../context/AuthContext";
import { IconCalendar, IconGoogle, IconMail } from "./icons";
import ScopeBadge from "./ScopeBadge";
import styles from "./GoogleConnectionCard.module.css";

const SCOPES = [
  { key: "calendar", label: "Calendar", icon: IconCalendar, url: "https://www.googleapis.com/auth/calendar" },
  { key: "gmail", label: "Gmail send", icon: IconMail, url: "https://www.googleapis.com/auth/gmail.send" },
];

/**
 * Reusable Google connection status + actions. `variant="summary"` is the
 * compact card used on the dashboard; `variant="full"` (default) is the
 * complete version used at /settings/google. Both read the same AuthContext
 * so they never go out of sync.
 */
export default function GoogleConnectionCard({ variant = "full" }) {
  const { user, refetch } = useAuth();
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState(null);

  const connected = Boolean(user?.google_connected);
  const granted = user?.granted_scopes || [];

  async function handleDisconnect() {
    if (variant === "summary") return;
    if (!window.confirm("Disconnect Google? You'll keep your WorkHire login, but lose Calendar/Gmail access until you reconnect.")) {
      return;
    }
    setBusy(true);
    setNotice(null);
    try {
      await api.disconnectGoogle();
      await refetch();
      setNotice({ tone: "success", text: "Google disconnected." });
    } catch (err) {
      setNotice({ tone: "danger", text: err.message || "Couldn't disconnect. Try again." });
    } finally {
      setBusy(false);
    }
  }

  function handleConnect() {
    window.location.href = api.googleLoginUrl();
  }

  return (
    <div className={`glass-card ${styles.card}`}>
      <div className={styles.header}>
        <span className={styles.iconWrap}>
          <IconGoogle />
        </span>
        <div>
          <h3 className={styles.title}>Google connection</h3>
          <p className={styles.subtitle}>
            {connected ? "Calendar and email access are linked to this account." : "Not connected yet."}
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

      {variant === "full" && (
        <>
          <div className={styles.actions}>
            <button className="btn btn-primary btn-sm" onClick={handleConnect} disabled={busy}>
              {connected ? "Reconnect Google" : "Connect Google"}
            </button>
            {connected && (
              <button className="btn btn-danger btn-sm" onClick={handleDisconnect} disabled={busy}>
                Disconnect
              </button>
            )}
          </div>
          {notice && (
            <p className={notice.tone === "danger" ? styles.noticeDanger : styles.noticeSuccess}>{notice.text}</p>
          )}
        </>
      )}
    </div>
  );
}
