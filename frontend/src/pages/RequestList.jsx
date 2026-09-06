import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import StatusPill from "../components/StatusPill";
import Spinner from "../components/Spinner";
import { IconChevronRight } from "../components/icons";
import styles from "./RequestList.module.css";

export default function RequestList() {
  const [items, setItems] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api
      .listRequests()
      .then(setItems)
      .catch((err) => setError(err.message || "Couldn't load requests."));
  }, []);

  return (
    <div className="animate-in">
      <div className={styles.header}>
        <div>
          <h1 className={`heading-display ${styles.heading}`}>Interview requests</h1>
          <p className={styles.subtitle}>Every request you or a teammate has created.</p>
        </div>
        <Link to="/requests/new" className="btn btn-primary">
          New request
        </Link>
      </div>

      {error && <p className="field-error">{error}</p>}
      {!items && !error && <Spinner label="Loading…" />}

      {items && items.length === 0 && (
        <div className={`glass-card ${styles.empty}`}>
          <p>No interview requests yet.</p>
        </div>
      )}

      {items && items.length > 0 && (
        <div className={styles.list}>
          {items.map(({ request, interview }) => (
            <Link key={request.request_id} to={`/requests/${request.request_id}`} className={`glass-card ${styles.row}`}>
              <div className={styles.rowMain}>
                <div className={styles.rowTitle}>
                  {request.interview_type.replaceAll("_", " ")} — {request.required_skills.join(", ")}
                </div>
                <div className={styles.rowMeta}>
                  {request.request_id} · {request.panelists_required} panelist
                  {request.panelists_required > 1 ? "s" : ""}
                  {interview ? ` · ${interview.seats.filter((s) => s.status === "accepted").length}/${interview.seats.length} confirmed` : ""}
                </div>
              </div>
              <StatusPill status={request.status} />
              <IconChevronRight width={18} height={18} className="text-muted" />
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
