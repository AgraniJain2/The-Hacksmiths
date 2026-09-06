import { useEffect, useState } from "react";
import { api } from "../lib/api";
import StatusPill from "../components/StatusPill";
import Spinner from "../components/Spinner";
import styles from "./InterviewerOffers.module.css";

export default function InterviewerOffers() {
  const [offers, setOffers] = useState(null);
  const [error, setError] = useState(null);
  const [busyKey, setBusyKey] = useState(null);

  function load() {
    api
      .myOffers()
      .then(setOffers)
      .catch((err) => setError(err.message || "Couldn't load your offers."));
  }

  useEffect(load, []);

  async function respond(interviewId, seatIndex, accept) {
    const key = `${interviewId}-${seatIndex}`;
    setBusyKey(key);
    setError(null);
    try {
      await api.respondToSeat(interviewId, seatIndex, accept);
      load();
    } catch (err) {
      setError(err.message || "Couldn't record your response.");
    } finally {
      setBusyKey(null);
    }
  }

  async function cancelSeat(interviewId) {
    setBusyKey(interviewId);
    setError(null);
    try {
      await api.interviewerCancelSeat(interviewId);
      load();
    } catch (err) {
      setError(err.message || "Couldn't cancel your seat.");
    } finally {
      setBusyKey(null);
    }
  }

  return (
    <div className="animate-in">
      <div className={styles.header}>
        <h1 className={`heading-display ${styles.heading}`}>My offers</h1>
        <p className={styles.subtitle}>Panel seats offered or confirmed to you.</p>
      </div>

      {error && <p className="field-error">{error}</p>}
      {!offers && !error && <Spinner label="Loading…" />}

      {offers && offers.length === 0 && (
        <div className={`glass-card ${styles.empty}`}>
          <p>Nothing yet — you'll see offers here as soon as a request needs your skills.</p>
        </div>
      )}

      {offers && offers.length > 0 && (
        <div className={styles.list}>
          {offers.map(({ interview, seat_index }) => {
            const seat = interview.seats[seat_index];
            const key = `${interview.interview_id}-${seat_index}`;
            return (
              <div key={key} className={`glass-card ${styles.card}`}>
                <div className={styles.info}>
                  <div className={styles.type}>{interview.interview_type.replaceAll("_", " ")}</div>
                  <div className={styles.time}>{new Date(interview.slot_start).toLocaleString()}</div>
                </div>
                <StatusPill status={seat.status} kind="seat" />
                <div className={styles.actions}>
                  {seat.status === "offered" && (
                    <>
                      <button
                        className="btn btn-primary btn-sm"
                        disabled={busyKey === key}
                        onClick={() => respond(interview.interview_id, seat_index, true)}
                      >
                        Accept
                      </button>
                      <button
                        className="btn btn-outline btn-sm"
                        disabled={busyKey === key}
                        onClick={() => respond(interview.interview_id, seat_index, false)}
                      >
                        Decline
                      </button>
                    </>
                  )}
                  {seat.status === "accepted" && (
                    <button
                      className="btn btn-danger btn-sm"
                      disabled={busyKey === interview.interview_id}
                      onClick={() => cancelSeat(interview.interview_id)}
                    >
                      Cancel my seat
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
