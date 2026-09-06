// Shared enums mirroring the backend's (app/scheduling/config.py's
// SENIORITY_ORDER, schemas.py's INTERVIEW_TYPES). Keep in sync manually —
// there's no shared schema package between the two yet.

export const SENIORITY_LEVELS = ["JUNIOR", "MID", "SENIOR", "STAFF", "PRINCIPAL"];

export const INTERVIEW_TYPES = ["SCREENING", "TECHNICAL_ROUND_1", "TECHNICAL_ROUND_2", "MANAGERIAL", "HR"];
