// Shared IANA timezone list — backs every timezone dropdown in the app
// (RequestNew.jsx's candidate timezone, InterviewerProfile.jsx's own
// timezone). No canonical list existed before this; `Intl.supportedValuesOf`
// is the browser's own live IANA database, so it's always current — the
// fallback below only matters for a browser old enough to lack it.
const FALLBACK_TIMEZONES = [
  "UTC",
  "America/Los_Angeles",
  "America/Denver",
  "America/Chicago",
  "America/New_York",
  "America/Sao_Paulo",
  "Europe/London",
  "Europe/Paris",
  "Europe/Berlin",
  "Europe/Moscow",
  "Africa/Cairo",
  "Africa/Johannesburg",
  "Asia/Dubai",
  "Asia/Kolkata",
  "Asia/Dhaka",
  "Asia/Bangkok",
  "Asia/Singapore",
  "Asia/Shanghai",
  "Asia/Tokyo",
  "Asia/Seoul",
  "Australia/Sydney",
  "Pacific/Auckland",
];

function loadTimezones() {
  try {
    if (typeof Intl.supportedValuesOf === "function") {
      return Intl.supportedValuesOf("timeZone");
    }
  } catch {
    // Fall through to the static list below.
  }
  return FALLBACK_TIMEZONES;
}

export const TIMEZONES = loadTimezones();

export function browserTimezone() {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}
