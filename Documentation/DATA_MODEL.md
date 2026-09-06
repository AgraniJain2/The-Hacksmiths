# Data Model

Source of truth is always `backend/app/db/models.py` — this doc explains the
*why* behind it; if the two disagree, the code is right and this doc is stale
(fix the doc).

**Status:** everything on this page is built (Phase 2,
Documentation/IMPLEMENTATION_PLAN.md) — `User`, `OAuthToken`, the extended
`Interview`, `InterviewerProfile`, `CandidateAvailabilityWindow`,
`InterviewSlotOffer`, `InterviewParticipant`, `InviteToken`. A handful of
columns below differ from what's actually in `models.py`, on purpose —
`app/db/models.py`'s `Interview` docstring lists each one and why (mostly:
the engine needs an email/name denormalized where this doc assumed a `User`
FK join, plus two JSON cache columns — `seats_json`, `feasibility_json` —
for engine state that has no independent DB representation of its own).
Don't "fix" those back to match this doc; per the header above, the code is
right there. Everything else below matches the code as shipped.

## Tables that exist today (built)

### `User`
One row per person, regardless of role.

| Column | Type | Notes |
|---|---|---|
| `id` | string (UUID) | PK |
| `google_id` | string, unique | Google's `sub` claim — the stable identity key, not email |
| `email` | string, unique | |
| `name` | string | |
| `role` | enum: `candidate`, `recruiter`, `hiring_manager`, `interviewer` | Set once at first login, see [AUTH_MODULE.md](AUTH_MODULE.md) |
| `status` | enum: `active`, `disabled` | Not enforced anywhere yet |
| `created_at` | datetime | |

### `OAuthToken`
One row per user (1:1), holding their Google tokens. See
[AUTH_MODULE.md](AUTH_MODULE.md) — never query this outside
`app/auth/google_oauth.py`.

## Tables to add (spec for Module 2 onward)

### `Interview` (extend the existing stub)
Currently just `id, title, status, created_by, created_at`. Extend with:

| Column | Type | Notes |
|---|---|---|
| `interview_type` | enum: `SCREENING`, `TECHNICAL_ROUND_1`, `TECHNICAL_ROUND_2`, `MANAGERIAL`, `HR` (extend as needed) | |
| `required_skills` | JSON array of strings | e.g. `["React", "System Design"]` — interviewer must match **all**, not any-overlap |
| `required_seniority` | enum: `JUNIOR`, `MID`, `SENIOR`, `STAFF` | minimum seniority to be pool-eligible |
| `panelists_required` | int | **N** — how many distinct interviewer seats this interview needs. Recruiter-specified at creation. |
| `hiring_manager_id` | string, FK → `users.id`, nullable | named explicitly by the recruiter, **not** pool-matched |
| `candidate_email`, `candidate_timezone` | string | |
| `duration_minutes`, `buffer_minutes` | int | |
| `status` | enum: `draft`, `collecting_availability`, `awaiting_candidate_selection`, `assigning_interviewers`, `scheduled`, `cancelled`, `completed`, `needs_recruiter_action` | `needs_recruiter_action` = Stage 4 found zero feasible slots, or Stage 6 exhausted the pool for an open seat |
| `confirmed_start_utc`, `confirmed_end_utc` | datetime, nullable | set once Stage 6 completes. Kept directly on `Interview` rather than a separate `Booking` table since an interview has at most one *active* confirmed time; a reschedule replaces these values rather than creating a parallel row |
| `calendar_event_id`, `meeting_link` | string, nullable | set by Module 7 after creating the Calendar event |

`panelists_required` is checked against the *count* of `confirmed`
`InterviewParticipant` rows with `role = 'panelist'` for this interview —
there's no separate `panelists_confirmed` counter column, for the same
reason load stats aren't stored counters either (see `InterviewerProfile`
below): a live count can't drift out of sync with cancellations.

### `InterviewerProfile` (new — Module 2B)
One row per interviewer, separate from `User` so not every user needs pool
metadata (candidates/recruiters don't have one).

| Column | Type | Notes |
|---|---|---|
| `id` | string (UUID) | PK |
| `user_id` | string, FK → `users.id`, unique | must be a `User` with `role = interviewer` |
| `skills` | JSON array of strings | self-declared or admin-set |
| `seniority` | enum: `JUNIOR`, `MID`, `SENIOR`, `STAFF` | |
| `qualified_interview_types` | JSON array of the `interview_type` enum values | which rounds this person can run |
| `active` | bool, default true | opt-out toggle for "don't assign me right now" (leave, overloaded) — independent of calendar busy/free |
| `timezone` | string (IANA, e.g. `Asia/Kolkata`) | **required** — working hours are meaningless without knowing what timezone they're in |
| `working_hours_start`, `working_hours_end` | time-of-day (e.g. `09:00`, `18:00`) | defaults to `09:00`–`18:00` in the interviewer's own `timezone` if never customized. This is what Module 4/6 clip candidate-matched slots to — raw Calendar free/busy alone would happily call 11pm "free" just because nothing's booked then |
| `updated_at` | datetime | |

**No `current_weekly_interviews` or `last_interview_at` columns here** —
deliberately. Both are **computed live from `InterviewParticipant`**, not
stored counters:

```
current_load(interviewer)   = COUNT(InterviewParticipant
                                     WHERE user_id = interviewer
                                       AND role = 'panelist'
                                       AND status = 'confirmed'
                                       AND created_at >= now - 7 days)

last_assigned_at(interviewer) = MAX(InterviewParticipant.created_at
                                     WHERE user_id = interviewer
                                       AND role = 'panelist'
                                       AND status = 'confirmed')
```

A stored counter would need manual increment on assignment and decrement on
cancellation — easy to get out of sync (a crashed request between "assign"
and "increment," a cancellation that forgets to decrement). Computing it from
`InterviewParticipant.status = 'confirmed'` means a cancellation (which flips
`status` to `cancelled`) automatically falls out of the count with no extra
code. Cost: a query instead of a field read — index
`InterviewParticipant(user_id, status, created_at)` to keep it cheap; if this
ever becomes a hot path at real scale, revisit with a maintained counter plus
a reconciliation job, but don't pre-optimize for that now.

### `CandidateAvailabilityWindow` (new — Module 3)
Candidate submits one or more free windows rather than a single slot.

| Column | Type | Notes |
|---|---|---|
| `id` | string (UUID) | PK |
| `interview_id` | string, FK → `interviews.id` | |
| `start_utc`, `end_utc` | datetime | stored in UTC; convert to/from the candidate's timezone only at the edges (display, input) |

### `InterviewSlotOffer` (new — Module 6)
One row per attempt to assign a specific interviewer to one of the
interview's open seats, at the interview's already-fixed time. **Up to
`panelists_required` non-terminal (`OFFERED`) rows can exist per interview at
once** — one per open seat, never more.

| Column | Type | Notes |
|---|---|---|
| `id` | string (UUID) | PK |
| `interview_id` | string, FK → `interviews.id` | |
| `interviewer_user_id` | string, FK → `users.id` | |
| `proposed_start_utc`, `proposed_end_utc` | datetime | the time the candidate picked in Stage 5 — identical across every offer row tied to one interview |
| `status` | enum: `OFFERED`, `ACCEPTED`, `DECLINED`, `EXPIRED` | `EXPIRED` = no response before `expires_at` — triggers the same per-seat cascade as an explicit decline |
| `offered_at`, `responded_at`, `expires_at` | datetime | `expires_at` drives the cascade timeout, checked by the same scheduled job that sends reminders (Module 8) |

Enforce "at most `panelists_required` `OFFERED` rows per interview" in
application logic inside the assignment transaction (a straight count check
before inserting) — a single global partial-unique-index trick (which worked
cleanly for the old N=1 design) doesn't extend to "at most N" without a
covering/filtered index keyed off a running count, which is more DB-specific
machinery than it's worth here.

**Assignment transaction** (creating any offer — initial batch or a cascade
step for one seat): lock the target interviewer's `InterviewerProfile` row
(`SELECT ... FOR UPDATE`), re-check they have no other `OFFERED` or confirmed
`InterviewParticipant` overlapping the proposed time (guards against a
*different* interview grabbing the same person for an overlapping slot),
then insert the `OFFERED` row. One row, one person, one check — this is
per-seat, not a seats-counter lock, because offers are always exactly 1:1
with open seats.

**On acceptance**: mark this offer `ACCEPTED`, create the
`InterviewParticipant` row for this seat. Once the count of `confirmed`
`InterviewParticipant` (`role='panelist'`) rows for this interview reaches
`panelists_required`, set `Interview.status = scheduled` and proceed to
Module 7.

**On decline/expiry**: mark this offer `DECLINED`/`EXPIRED`, recompute the
ranking excluding every interviewer already tried for *this seat's line of
offers* (interviewers already confirmed on other seats of the same interview
are also excluded, obviously), and either create the next `OFFERED` row for
this seat or — if nobody's left — set `Interview.status = needs_recruiter_action`.

### `InterviewParticipant` (new — confirmed roster only)
Created only once someone is actually locked in — a hiring manager at
creation time, or an interviewer on offer acceptance. Not where pending
offers live (that's `InterviewSlotOffer`) — this is the final roster, and
also what the load-balancing and `panelists_required` count queries read from.

| Column | Type | Notes |
|---|---|---|
| `id` | string (UUID) | PK |
| `interview_id` | string, FK → `interviews.id` | |
| `user_id` | string, FK → `users.id` | |
| `role` | enum: `hiring_manager`, `panelist` | up to `panelists_required` `panelist` rows per interview now |
| `status` | enum: `confirmed`, `cancelled` | flipped to `cancelled` when a confirmed interviewer backs out post-acceptance (Stage 8), which is what triggers that one seat's replacement cascade — and what makes them fall out of the live `panelists_required` count and load-balancing count automatically |
| `created_at` | datetime | this is the timestamp the load-balancing queries above key off of |

### `InviteToken` (existing, unchanged)
See earlier sections — still how a candidate authenticates against a
specific interview. No change from the pooling redesign.

## Relationships

```mermaid
erDiagram
    USER ||--o| OAUTH_TOKEN : has
    USER ||--o| INTERVIEWER_PROFILE : has
    USER ||--o{ INTERVIEW : "created_by (recruiter)"
    INTERVIEW ||--o{ CANDIDATE_AVAILABILITY_WINDOW : "candidate submits"
    INTERVIEW ||--o{ INTERVIEW_SLOT_OFFER : "up to N concurrent offers"
    USER ||--o{ INTERVIEW_SLOT_OFFER : "receives"
    INTERVIEW ||--o{ INTERVIEW_PARTICIPANT : "confirmed roster (up to N panelists + 1 hiring manager)"
    USER ||--o{ INTERVIEW_PARTICIPANT : "participates as"
    INTERVIEW ||--o{ INVITE_TOKEN : "issued for"
```

## Migrations

We use Alembic, autogenerating from the SQLAlchemy models — don't hand-write
migrations unless autogenerate gets something wrong.

```bash
cd backend
python -m alembic revision --autogenerate -m "short description of the change"
# review the generated file in alembic/versions/, then:
python -m alembic upgrade head
```

Do the `Interview` extension and the new tables above as **one migration**
if you're building Module 2/2B together, so `Interview`'s new columns and
`InterviewerProfile` land in the same reviewable change — don't apply half of
this spec and leave `Interview` in a half-migrated state for others to build
against.
