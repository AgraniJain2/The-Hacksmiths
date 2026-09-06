import { useEffect, useState } from "react";
import { api } from "../lib/api";
import Spinner from "../components/Spinner";
import styles from "./Notifications.module.css";

export default function Notifications() {
  const [items, setItems] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api
      .myNotifications()
      .then(setItems)
      .catch((err) => setError(err.message || "Couldn't load notifications."));
  }, []);

  return (
    <div className="animate-in">
      <div className={styles.header}>
        <h1 className={`heading-display ${styles.heading}`}>Notifications</h1>
        <p className={styles.subtitle}>
          Stand-in for real email — there's no Notification Service wired up yet.
        </p>
      </div>

      {error && <p className="field-error">{error}</p>}
      {!items && !error && <Spinner label="Loading…" />}

      {items && items.length === 0 && (
        <div className={`glass-card ${styles.empty}`}>
          <p>Nothing yet.</p>
        </div>
      )}

      {items && items.length > 0 && (
        <div className={styles.list}>
          {items.map((n) => (
            <div key={n.id} className={`glass-card ${styles.row}`}>
              <span className={styles.dot} />
              <div className={styles.body}>
                <div className={styles.message}>{n.message}</div>
                <div className={styles.time}>{new Date(n.created_at).toLocaleString()}</div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
