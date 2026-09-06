import { requestStatusMeta, seatStatusMeta } from "../lib/status";

/** `kind="request"` uses InterviewRequest/Interview status strings,
 * `kind="seat"` uses InterviewSeat status strings — see lib/status.js. */
export default function StatusPill({ status, kind = "request" }) {
  const meta = kind === "seat" ? seatStatusMeta(status) : requestStatusMeta(status);
  return <span className={`pill ${meta.pill}`}>{meta.label}</span>;
}
