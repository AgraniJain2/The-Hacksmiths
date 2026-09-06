import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../lib/api";
import StatusPill from "../components/StatusPill";
import Spinner from "../components/Spinner";
import { IconAlert, IconCalendar, IconCheck } from "../components/icons";
import styles from "./RequestDetail.module.css";

export default function RequestDetail() {
  const { requestId } = useParams();
  const [detail, setDetail] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api
      .getRequest(requestId)
      .then(setDetail)
      .catch((err) => setError(err.message || "Couldn't load this request."));
  }, [requestId]);

  if (error) return <p className="field-error">{error}</p>;
  if (!detail) return <Spinner label="Loading…" />;

  const { request, round, feasibility, interview } = detail;

  return (
    <div className="animate-in">
      <div className={styles.header}>
        <div>
          <h1 className={`heading-display ${styles.heading}`}>
            {request.interview_type.replaceAll("_", " ")}
          </h1>
          <div className={styles.meta}>
            <StatusPill status={request.status} />
            <span className="pill pill-neutral font-mono">{request.request_id}</span>
          </div>
        </div>
        <Link to="/requests" className="btn btn-ghost btn-sm">
          Back to all requests
        </Link>
      </div>

      {feasibility?.reauth_required_interviewer_ids?.length > 0 && (
        <div className={styles.reauthNotice}>
          <IconAlert width={16} height={16} style={{ display: "inline", verticalAlign: "-3px", marginRight: 6 }} />
          {feasibility.reauth_required_interviewer_ids.length === 1
            ? "1 potential panelist couldn't be checked — their Google connection needs to be reconnected."
            : `${feasibility.reauth_required_interviewer_ids.length} potential panelists couldn't be checked — their Google connections need to be reconnected.`}
        </div>
      )}

      {request.status === "manual_scheduling_required" && feasibility?.no_match_reason && (
        <div className={styles.escalation} style={{ marginBottom: "1.5rem" }}>
          <p className={styles.escalationTitle}>
            <IconAlert width={16} height={16} style={{ display: "inline", verticalAlign: "-3px", marginRight: 6 }} />
            Needs manual scheduling
          </p>
          <p>{feasibility.no_match_reason}</p>
        </div>
      )}

      {interview?.status === "panel_complete" && (
        <div className={styles.bookedCard}>
          <IconCheck width={20} height={20} className={styles.bookedIcon} />
          <div>
            <p className={styles.bookedTitle}>Booked — {new Date(interview.slot_start).toLocaleString()}</p>
            {interview.meet_link ? (
              <a href={interview.meet_link} target="_blank" rel="noreferrer" className={styles.bookedLink}>
                <IconCalendar width={14} height={14} style={{ marginRight: 4 }} />
                Join Google Meet
              </a>
            ) : (
              <p className={styles.bookedSubtitle}>Calendar invite is being created…</p>
            )}
          </div>
        </div>
      )}

      <div className={styles.grid}>
        <div className={`glass-card ${styles.card}`}>
          <p className={styles.cardTitle}>Request</p>
          <dl className={styles.kv}>
            <dt>Skills</dt>
            <dd>{request.required_skills.join(", ")}</dd>
            <dt>Seniority</dt>
            <dd>{request.seniority}+</dd>
            <dt>Panelists</dt>
            <dd>{request.panelists_required}</dd>
            <dt>Duration</dt>
            <dd>{round.duration_minutes}m (buffer {round.buffer_minutes_before}/{round.buffer_minutes_after}m)</dd>
            <dt>Hiring manager</dt>
            <dd>{request.hiring_manager_email || "—"}</dd>
            <dt>Candidate</dt>
            <dd>{request.candidate_id}</dd>
          </dl>
        </div>

        {feasibility && feasibility.feasible_slots.length > 0 && !interview && (
          <div className={`glass-card ${styles.card}`}>
            <p className={styles.cardTitle}>Feasible slots ({feasibility.feasible_slots.length})</p>
            <div className={styles.slotList}>
              {feasibility.feasible_slots.map((s) => (
                <div key={s.slot_id} className={styles.slotRow}>
                  <span>{new Date(s.start).toLocaleString()}</span>
                  <span className="text-muted">{s.feasible_count} eligible</span>
                </div>
              ))}
            </div>
            <p className="field-hint" style={{ marginTop: "0.75rem" }}>
              Waiting on the candidate to pick one.
            </p>
          </div>
        )}

        {interview && (
          <div className={`glass-card ${styles.card}`}>
            <p className={styles.cardTitle}>
              Panel — {new Date(interview.slot_start).toLocaleString()}
            </p>
            {interview.seats.map((seat) => (
              <div key={seat.seat_index} className={styles.seatRow}>
                <span className={styles.seatIndex}>#{seat.seat_index + 1}</span>
                <span className={styles.seatInterviewer}>
                  {seat.interviewer_id || <span className="text-muted">unfilled</span>}
                </span>
                <StatusPill status={seat.status} kind="seat" />
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
