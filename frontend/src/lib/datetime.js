// Shared date/time rendering — every page that shows an interview time
// should go through here rather than calling toLocaleString() inline, so the
// viewer's timezone is always shown explicitly (not just silently applied).
// Requires the backend to send timezone-aware ISO strings (see
// SchedulingService._row_to_interview's ensure_utc() calls) — Date() parses
// an offset-less string as local time, which is exactly the "shows UTC" bug
// this format is meant to make visible instead of hiding.

const DATE_TIME_FORMAT = {
  weekday: "short",
  month: "short",
  day: "numeric",
  hour: "numeric",
  minute: "2-digit",
  timeZoneName: "short",
};

const TIME_FORMAT = { hour: "numeric", minute: "2-digit", timeZoneName: "short" };

const DAY_FORMAT = { weekday: "short", month: "short", day: "numeric" };

/** Full "Tue, Sep 10, 2:00 PM IST" style string for a Date (or ISO string). */
export function formatDateTime(value) {
  const date = value instanceof Date ? value : new Date(value);
  return date.toLocaleString(undefined, DATE_TIME_FORMAT);
}

/** Time-only "2:00 PM IST" — for rows that already show the date separately. */
export function formatTime(value) {
  const date = value instanceof Date ? value : new Date(value);
  return date.toLocaleTimeString(undefined, TIME_FORMAT);
}

/** Date-only "Tue, Sep 10" — no timezone (a calendar day doesn't have one). */
export function formatDay(value) {
  const date = value instanceof Date ? value : new Date(value);
  return date.toLocaleDateString(undefined, DAY_FORMAT);
}
