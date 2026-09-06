// Shared enums mirroring the backend's (app/scheduling/config.py's
// SENIORITY_ORDER, schemas.py's INTERVIEW_TYPES). Keep in sync manually —
// there's no shared schema package between the two yet.

export const SENIORITY_LEVELS = ["JUNIOR", "MID", "SENIOR", "STAFF", "PRINCIPAL"];

// Recruiter-side only — a request names a specific round (RequestNew.jsx).
export const INTERVIEW_TYPES = ["SCREENING", "TECHNICAL_ROUND_1", "TECHNICAL_ROUND_2", "MANAGERIAL", "HR"];

// Interviewer-side qualification types (InterviewerProfile.jsx). "TECHNICAL"
// is generic on purpose — which round a request is for isn't a qualification
// distinction, so interviewers don't pick Round 1 vs Round 2; the backend's
// pool-matching (app/scheduling/pool.py's `_type_ok`) treats "TECHNICAL" as
// satisfying either TECHNICAL_ROUND_1 or TECHNICAL_ROUND_2 requests.
export const INTERVIEWER_QUALIFICATION_TYPES = ["SCREENING", "TECHNICAL", "MANAGERIAL", "HR"];

// Canonical skill list shared by the recruiter's "required skills" field and
// the interviewer's "skills" field — a fixed vocabulary instead of free text
// on either side is what makes the subset-match in pool.py actually work
// (freeform "React" vs "react" vs "ReactJS" would silently never match).
export const SKILLS = [
  "JavaScript",
  "TypeScript",
  "Python",
  "Java",
  "Go",
  "Rust",
  "SQL",
  "React",
  "Node.js",
  "System Design",
  "Algorithms",
  "Data Structures",
  "Distributed Systems",
  "Cloud Infrastructure",
  "DevOps",
  "Security",
  "Machine Learning",
  "Data Engineering",
  "Mobile Development",
  "Leadership",
];
