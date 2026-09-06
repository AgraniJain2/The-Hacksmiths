import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { useAuth } from "../context/AuthContext";
import Spinner from "../components/Spinner";
import StatusPill from "../components/StatusPill";
import ActivityCalendar from "../components/ActivityCalendar";
import { IconAlert, IconCheck } from "../components/icons";
import styles from "./Candidate.module.css";

function emptyWindow() {
  return { start: "", end: "" };
}

export default function Candidate() {
  const { user } = useAuth();
  const [detail, setDetail] = useState(undefined); // undefined = loading, null = no request
  const [error, setError] = useState(null);
  const [windows, setWindows] = useState([emptyWindow()]);
  const [busy, setBusy] = useState(false);
  const [rescheduling, setRescheduling] = useState(false);
  const [rescheduleWindows, setRescheduleWindows] = useState([emptyWindow()]);

  function load() {
    api
      .myRequest()
      .then(setDetail)
      .catch((err) => setError(err.message || "Couldn't load your interview."));
  }

  useEffect(load, []);

  function setWindow(i, key, value) {
    setWindows((ws) => ws.map((w, idx) => (idx === i ? { ...w, [key]: value } : w)));
  }

  async function submitAvailability(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const payload = windows
        .filter((w) => w.start && w.end)
        .map((w) => ({
          start: new Date(w.start).toISOString(),
          end: new Date(w.end).toISOString(),
          source_timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
        }));
      if (payload.length === 0) throw new Error("Add at least one time window.");
      await api.submitAvailability(detail.request.request_id, payload);
      load();
    } catch (err) {
      setError(err.message || "Couldn't submit your availability.");
    } finally {
      setBusy(false);
    }
  }

  async function pickSlot(slotId) {
    setBusy(true);
    setError(null);
    try {
      await api.selectSlot(detail.request.request_id, slotId);
      load();
    } catch (err) {
      setError(err.message || "Couldn't select that slot.");
    } finally {
      setBusy(false);
    }
  }

  async function cancel() {
    if (!window.confirm("Cancel this interview?")) return;
    setBusy(true);
    try {
      await api.cancelRequest(detail.request.request_id);
      load();
    } catch (err) {
      setError(err.message || "Couldn't cancel.");
    } finally {
      setBusy(false);
    }
  }

  function setRescheduleWindow(i, key, value) {
    setRescheduleWindows((ws) => ws.map((w, idx) => (idx === i ? { ...w, [key]: value } : w)));
  }

  async function submitReschedule(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const payload = rescheduleWindows
        .filter((w) => w.start && w.end)
        .map((w) => ({
          start: new Date(w.start).toISOString(),
          end: new Date(w.end).toISOString(),
          source_timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
        }));
      if (payload.length === 0) throw new Error("Add at least one time window.");
      await api.rescheduleRequest(detail.request.request_id, payload);
      setRescheduling(false);
      setRescheduleWindows([emptyWindow()]);
      load();
    } catch (err) {
      setError(err.message || "Couldn't reschedule.");
    } finally {
      setBusy(false);
    }
  }

  if (detail === undefined) return <Spinner label="Loading your interview…" />;

  if (detail === null) {
    return (
      <div className={`animate-in ${styles.wrap}`}>
        <div className={`glass-card ${styles.card} ${styles.center}`}>
          <h1 className="heading-display" style={{ fontSize: "1.4rem" }}>
            No interview found
          </h1>
          <p className="text-secondary" style={{ marginTop: "0.5rem" }}>
            We couldn't find an interview request for {user?.email}. Check the invite link, or ask
            your recruiter.
          </p>
        </div>
      </div>
    );
  }

  const { request, feasibility, interview } = detail;

  return (
    <div className={`animate-in ${styles.wrap}`}>
      <div className={styles.header}>
        <h1 className={`heading-display ${styles.heading}`}>
          Your {request.interview_type.replaceAll("_", " ")} interview
        </h1>
        <StatusPill status={request.status} />
      </div>

      {error && <p className="field-error" style={{ marginBottom: "1rem" }}>{error}</p>}

      {request.status === "collecting_availability" && (
        <form className={`glass-card ${styles.card}`} onSubmit={submitAvailability}>
          <p className="text-secondary" style={{ marginBottom: "1.25rem" }}>
            Add every window you're free — times use your own device's timezone.
          </p>
          {windows.map((w, i) => (
            <div key={i} className={styles.windowRow}>
              <input
                type="datetime-local"
                className="input"
                required
                value={w.start}
                onChange={(e) => setWindow(i, "start", e.target.value)}
              />
              <span className="text-muted">to</span>
              <input
                type="datetime-local"
                className="input"
                required
                value={w.end}
                onChange={(e) => setWindow(i, "end", e.target.value)}
              />
              {windows.length > 1 && (
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  onClick={() => setWindows((ws) => ws.filter((_, idx) => idx !== i))}
                >
                  Remove
                </button>
              )}
            </div>
          ))}
          <div className={styles.addRow}>
            <button type="button" className="btn btn-outline btn-sm" onClick={() => setWindows((ws) => [...ws, emptyWindow()])}>
              + Add another window
            </button>
          </div>
          <button className="btn btn-primary" type="submit" disabled={busy}>
            {busy ? "Submitting…" : "Submit availability"}
          </button>
        </form>
      )}

      {request.status === "awaiting_candidate_selection" && feasibility && (
        <div className={`glass-card ${styles.card}`}>
          <p className="text-secondary" style={{ marginBottom: "1rem" }}>
            Pick whichever time works best for you — everyone on the panel is available at each
            option below.
          </p>
          <div className={styles.slotList}>
            {feasibility.feasible_slots.map((s) => (
              <button key={s.slot_id} className={styles.slotButton} disabled={busy} onClick={() => pickSlot(s.slot_id)}>
                <span>{new Date(s.start).toLocaleString()}</span>
                <span className="btn btn-outline btn-sm">Select</span>
              </button>
            ))}
          </div>
        </div>
      )}

      {request.status === "manual_scheduling_required" && (
        <div className={styles.escalation}>
          <IconAlert width={28} height={28} style={{ margin: "0 auto 0.75rem", color: "var(--danger)" }} />
          <p style={{ fontWeight: 700, marginBottom: "0.5rem" }}>We need a hand with this one</p>
          <p className="text-secondary">
            {feasibility?.candidate_message ||
              "We couldn't find a time that works for everyone yet. A recruiter has been notified and will follow up with you directly."}
          </p>
        </div>
      )}

      {interview && (request.status === "assigning_panel" || request.status === "panel_complete") && (
        <div className={`glass-card ${styles.card} ${styles.center}`}>
          {request.status === "panel_complete" ? (
            <IconCheck width={32} height={32} className={styles.bookedIcon} />
          ) : (
            <Spinner size={28} />
          )}
          <h2 className="heading-display" style={{ fontSize: "1.3rem", marginTop: "0.5rem" }}>
            {request.status === "panel_complete" ? "You're booked" : "Confirming your interviewers…"}
          </h2>
          <p className="text-secondary" style={{ marginTop: "0.5rem" }}>
            {new Date(interview.slot_start).toLocaleString()}
            <br />
            {request.status === "panel_complete"
              ? "Your panel is fully confirmed."
              : `Waiting on ${interview.seats.length - interview.seats.filter((s) => s.status === "accepted").length} of ${interview.seats.length} interviewers to confirm.`}
          </p>
          {request.status === "panel_complete" && (
            interview.meet_link ? (
              <a
                href={interview.meet_link}
                target="_blank"
                rel="noreferrer"
                className="btn btn-primary"
                style={{ marginTop: "1rem" }}
              >
                Join Google Meet
              </a>
            ) : (
              <p className="field-hint" style={{ marginTop: "1rem" }}>
                Your calendar invite and Meet link are being created — check your email shortly.
              </p>
            )
          )}
          <div style={{ display: "flex", gap: "0.5rem", justifyContent: "center", marginTop: "1rem" }}>
            <button
              className="btn btn-outline"
              onClick={() => setRescheduling((v) => !v)}
              disabled={busy}
            >
              {rescheduling ? "Never mind" : "Reschedule"}
            </button>
            <button className="btn btn-outline" onClick={cancel} disabled={busy}>
              Cancel interview
            </button>
          </div>
        </div>
      )}

      {rescheduling && interview && (
        <form className={`glass-card ${styles.card}`} style={{ marginTop: "1.5rem" }} onSubmit={submitReschedule}>
          <p className="text-secondary" style={{ marginBottom: "1.25rem" }}>
            This releases your current time and every confirmed interviewer's seat — add the
            windows that work for you now, and we'll find a new panel.
          </p>
          {rescheduleWindows.map((w, i) => (
            <div key={i} className={styles.windowRow}>
              <input
                type="datetime-local"
                className="input"
                required
                value={w.start}
                onChange={(e) => setRescheduleWindow(i, "start", e.target.value)}
              />
              <span className="text-muted">to</span>
              <input
                type="datetime-local"
                className="input"
                required
                value={w.end}
                onChange={(e) => setRescheduleWindow(i, "end", e.target.value)}
              />
              {rescheduleWindows.length > 1 && (
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  onClick={() => setRescheduleWindows((ws) => ws.filter((_, idx) => idx !== i))}
                >
                  Remove
                </button>
              )}
            </div>
          ))}
          <div className={styles.addRow}>
            <button
              type="button"
              className="btn btn-outline btn-sm"
              onClick={() => setRescheduleWindows((ws) => [...ws, emptyWindow()])}
            >
              + Add another window
            </button>
          </div>
          <button className="btn btn-primary" type="submit" disabled={busy}>
            {busy ? "Submitting…" : "Confirm reschedule"}
          </button>
        </form>
      )}

      {interview && request.status === "panel_complete" && (
        <div style={{ marginTop: "1.5rem" }}>
          <ActivityCalendar
            events={[
              {
                id: interview.interview_id,
                title: request.interview_type.replaceAll("_", " "),
                subtitle: "Your interview",
                start: new Date(interview.slot_start),
                status: <StatusPill status={interview.status} />,
              },
            ]}
          />
        </div>
      )}

      {request.status === "cancelled" && (
        <div className={`glass-card ${styles.card} ${styles.center}`}>
          <p>This interview was cancelled.</p>
        </div>
      )}
    </div>
  );
}
