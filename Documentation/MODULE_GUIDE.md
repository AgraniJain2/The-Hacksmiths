# Module Guide — Pick One, Hand This to Your AI Agent

**Status:** every module below (2 through 8) is now built — see
[IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) for what actually shipped
and where. This doc is kept as the original build brief / design record (the
goals, edge cases, and "which function to call" pointers below are still
accurate reference material), not as a "still to do" list — a mention of the
`Interview` "stub" below is historical (true before Module 2 was built, not
now: `app/scheduling/service.py` owns the real table DATA_MODEL.md
describes).

Each section below is written to be handed to an AI coding agent as the brief
for that module — goal, what already exists to build on, what to build, and
exactly which existing function to call for auth/Google access. Cross-read
[AUTH_MODULE.md](AUTH_MODULE.md), [DATA_MODEL.md](DATA_MODEL.md), and
[WORKFLOW.md](WORKFLOW.md) first; this guide assumes all three.

General rule for every module: **create a new folder under `backend/app/`**
(e.g. `app/interviews/`, `app/scheduling/`, `app/notifications/`) mirroring
the structure of `app/auth/` — a `router.py` for endpoints, and whatever
service/logic files make sense. Add new tables to `app/db/models.py` and run
an Alembic migration (see [DATA_MODEL.md](DATA_MODEL.md#migrations)). Register
your router in `app/main.py` the same way `auth_router`/`google_router` are.

**Build the Notification Service first, or in parallel with Module 2** —
Modules 6, 7, and 8 all need to send emails (offer notifications,
confirmations, reminders, cancellations), and duplicating that integration
three times is exactly the kind of avoidable rework the hackathon guidelines
call out. See the shared section at the bottom before starting Module 6.

---

## Module 2 — Interview Request

**Goal**: recruiter creates an interview request — requirements only, no
named panelist.

**Depends on**: `get_current_user` (only recruiters/hiring_managers should be
able to create one — check `user.role`), the `Interview` stub in
`app/db/models.py`.

**Build**:
- Extend `Interview` per [DATA_MODEL.md](DATA_MODEL.md#interview-extend-the-existing-stub):
  `interview_type`, `required_skills`, `required_seniority`,
  **`panelists_required`**, `hiring_manager_id`, candidate email/timezone,
  duration/buffer, the new `status` enum.
- `POST /interviews` — create one (recruiter/hiring_manager only). Validates
  `required_skills` non-empty, `duration_minutes > 0`, **`panelists_required >= 1`**,
  candidate email well-formed.
- `GET /interviews/{id}` — fetch details + current status + how many seats
  are confirmed so far (`count of InterviewParticipant role='panelist' status='confirmed'` vs `panelists_required`).
- On creation, mint an `InviteToken` for the candidate and hand it to the
  Notification Service to email.

**Edge cases**: empty/malformed candidate email, zero-length
`required_skills`, `panelists_required` higher than the number of currently
active interviewers matching the skill/seniority/type combo at all (worth a
warning at creation time, not just a silent failure later in Stage 4).

---

## Module 2B — Interviewer Pool Profile

**Goal**: let interviewers declare what they're qualified for, their working
hours, and toggle availability for assignment.

**Depends on**: `get_current_user` with `role == "interviewer"`.

**Build**:
- `InterviewerProfile` table, per [DATA_MODEL.md](DATA_MODEL.md#interviewerprofile-new--module-2b)
  — **including `timezone`, `working_hours_start`, `working_hours_end`**,
  which is new in this revision.
- `PUT /me/interviewer-profile` — upsert your own skills/seniority/qualified
  types/active flag/timezone/working hours. Interviewer-only. Default working
  hours to `09:00`–`18:00` in whatever timezone they report if they don't
  set custom ones.
- `GET /me/interviewer-profile` — read your own.
- Self-declared, no approval workflow — simplest for hackathon scope, flag
  as a known simplification if asked in the walkthrough.

**Edge cases**: an interviewer with `role == "interviewer"` who never creates
a profile (treat as inactive/ineligible everywhere — an optional lookup, not
an assumed row). A `working_hours_start` after `working_hours_end` (reject,
don't silently produce an empty or inverted window).

---

## Module 3 — Candidate Availability Collection

**Goal**: candidate (already logged in via their invite link) submits the
time windows they're free.

**Depends on**: candidate login already works (built — see
[AUTH_MODULE.md](AUTH_MODULE.md)).

**Build**:
- `CandidateAvailabilityWindow` table, per [DATA_MODEL.md](DATA_MODEL.md#candidateavailabilitywindow-new--module-3).
- `POST /interviews/{id}/availability` — candidate-role-only, submits one or
  more `{start, end}` windows in their own timezone (explicit, never
  inferred from browser locale/IP).
- Update `Interview.status` to `collecting_availability` →
  `awaiting_candidate_selection` once Module 4 has produced feasible slots.

**Edge cases**: overlapping submitted windows (dedupe/merge), a window
shorter than `duration_minutes + buffer_minutes` (filter out, don't pass
through to Module 4 as valid), candidate resubmitting after already picking
a slot (replace prior windows, don't append stale ones).

---

## Module 4 — Interviewer Pool Feasibility Check

**Goal**: given an interview's requirements (including `panelists_required`)
and the candidate's submitted windows, return which windows have **at least
N** eligible, working-hours-respecting, calendar-free interviewers.

**Depends on**: `get_valid_access_token(db, user_id)` from
`app.auth.google_oauth` — never touch `OAuthToken` rows directly. Also
depends on Module 2B's `InterviewerProfile` (skills/seniority/type/active
**and now timezone/working hours**) and Module 3's availability windows.

**Build**:
- Query eligible interviewers: `InterviewerProfile.active = true`,
  `required_seniority` satisfied, `interview_type` in
  `qualified_interview_types`, **all** `required_skills` present (subset
  match, not any-overlap).
- For each eligible interviewer, for each candidate window, check **three**
  conditions — all must hold for that sub-slot to count:
  1. Calendar `freebusy.query` (via `get_valid_access_token`) shows them free
  2. The sub-slot falls inside `working_hours_start`–`working_hours_end`,
     **converted through that interviewer's own `timezone`** — never assume
     a shared timezone across the pool, and never skip this check just
     because the calendar says "free" (an empty calendar at 11pm is still
     free, just not appropriate)
  3. It respects `buffer_minutes` around that interviewer's adjacent events
- A candidate window is feasible only if **at least `panelists_required`**
  distinct interviewers pass all three checks for it.
- **Explicit "insufficient coverage" response** if no window clears the bar
  — say which constraint is the blocker (not enough qualified people at all,
  vs. enough people but outside working hours, vs. everyone's just busy) so
  the recruiter/candidate knows what to actually fix.

**Edge cases**: an eligible interviewer with a dead Google connection
(`ReauthRequired`) shouldn't silently vanish from every slot forever without
surfacing that they need to reconnect. DST transitions — store/compare in
UTC, convert to each interviewer's local time only for the working-hours
check itself. A window where exactly N interviewers are feasible but one of
them has borderline working hours (e.g., the slot is at their very last
working minute) — don't special-case this, just apply the same clean
boundary check as everywhere else (inclusive/exclusive, pick one and be
consistent).

---

## Module 5 — Candidate Slot Selection

**Goal**: candidate picks one exact time from Module 4's feasible list.

**Depends on**: Module 4's output.

**Build**:
- `GET /interviews/{id}/slots` — candidate-role-only, returns the feasible
  windows converted to the candidate's timezone.
- `POST /interviews/{id}/slots/select` — candidate picks one exact
  `{start, end}`; sets `Interview.status = assigning_interviewers` and hands
  off to Module 6.

**Edge cases**: idempotency (double-submit shouldn't trigger two separate
Module 6 assignment runs — check current `Interview.status` first), the
picked slot no longer being feasible by submission time (re-validate against
Module 4's logic live, don't trust a stale client-side list).

---

## Module 6 — N-Seat Interviewer Assignment

**Goal**: the core logic. Given the interview's now-fixed time and
`panelists_required` = N, fill all N seats with distinct interviewers,
picked deterministically by load, with a fast parallel path and a
per-seat fallback cascade.

**Depends on**: `get_valid_access_token`, `InterviewerProfile` (including
working hours), the `InterviewSlotOffer` table, the Notification Service.

**Build**:
1. **Ranking function**: eligible-and-feasible-at-the-fixed-time
   interviewers (same three-condition check as Module 4 — calendar-free,
   within working hours, buffer-respecting — re-checked live), ordered by
   the two computed queries in
   [DATA_MODEL.md](DATA_MODEL.md#interviewerprofile-new--module-2b) — lowest
   rolling 7-day confirmed count first, least-recently-assigned as tiebreak.
2. **Initial batch**: take the top N from the ranking and create one
   `InterviewSlotOffer` per seat, **in parallel** — this is the "top N
   simultaneous offers" step, not a broadcast to the whole eligible pool
   (only exactly N people get notified, one seat each).
3. **Offer creation transaction** (used for the initial batch *and* every
   later cascade step for a single seat): lock the target interviewer's
   `InterviewerProfile` row, re-verify no overlapping `OFFERED` or confirmed
   `InterviewParticipant` exists for them (guards against a different
   interview grabbing the same person moments apart), insert the offer row
   (`expires_at` = now + your chosen timeout, e.g. 2 hours), then have the
   Notification Service send accept/decline links (signed, single-use, same
   pattern as `InviteToken`).
4. **`POST /offers/{id}/accept`** (via the signed link, no login required):
   in a transaction, verify the offer is still `OFFERED` and unexpired, mark
   it `ACCEPTED`, create the `InterviewParticipant` row for that seat. If the
   confirmed-panelist count now equals `panelists_required`, set
   `Interview.status = scheduled` and hand off to Module 7 — otherwise, this
   seat is just done; the other seats' offers continue independently.
5. **`POST /offers/{id}/decline`** and the **expiry sweep** (scheduled job,
   same infra as Module 8's reminders) both trigger the same per-seat
   cascade: mark the offer `DECLINED`/`EXPIRED`, re-rank excluding everyone
   already tried *for this seat* and everyone already confirmed on *any*
   seat of this interview, and either create the next offer for this one
   seat or — if nobody's left — set `Interview.status = needs_recruiter_action`.

**Edge cases**: `panelists_required` greater than the total eligible pool
size (immediate escalation for the seats that can never be filled — don't
spin forever). Two seats' cascades independently trying to land on the same
next-ranked candidate at the same moment (the per-offer lock in step 3
handles this — whichever transaction commits first wins the row, the second
sees the conflict and moves to the next candidate in its own ranking). All N
initial offers declining simultaneously (should cascade all N seats
independently and correctly, not just the first one).

---

## Module 7 — Event Creation & Dispatch

**Goal**: once Module 6 fills every seat, create one calendar event and
notify everyone.

**Depends on**: `get_valid_access_token` (recruiter's or an organizer's token
to create the event), the Notification Service.

**Build**:
- Calendar API `events.insert` with `conferenceData: {createRequest: {...}}`
  and `conferenceDataVersion=1` for the Meet link.
- Attendees: candidate + hiring manager (if named) + **all N confirmed
  interviewers**.
- Store the event id on `Interview.calendar_event_id`, the Meet link on
  `Interview.meeting_link`.
- Send confirmation email to everyone via the Notification Service, `.ics`
  attached as a fallback for non-Google participants.

**Edge cases**: event creation succeeds but notification send fails (or vice
versa) — don't leave a half-done booking; make both steps individually
retryable/idempotent (check `calendar_event_id` is already set before
creating a duplicate on retry).

---

## Module 8 — Post-Booking & Exception Handling

**Goal**: reminders before the interview; both parties can cancel/reschedule,
with per-seat granularity for interviewer cancellations.

**Depends on**: Module 7's booking + calendar event, Module 6's
ranking/cascade logic (reused here, scoped to one seat), a scheduled job
runner (a simple polling loop or APScheduler is enough for hackathon scope).

**Build**:
- A scheduled job finding bookings starting soon and sending reminders —
  the same job can also run Module 6's offer-expiry sweep.
- `POST /interviews/{id}/cancel` (candidate) — release **all** confirmed
  interviewer seats (flip each `InterviewParticipant.status` to `cancelled`,
  which drops them from the live load-balancing count automatically), notify
  them it's off, reset `Interview.status` back to `collecting_availability`.
- `POST /interviews/{id}/reschedule` (candidate) — same release as cancel,
  expects new/updated availability windows, loops back to Module 3.
- `POST /interviews/{id}/interviewer-cancel` (a confirmed interviewer, via a
  signed link or authenticated session) — flip **only their own**
  `InterviewParticipant` to `cancelled`, then re-run Module 6's
  ranking/cascade for **that one seat**, at the same fixed time, excluding
  this interviewer. The candidate's confirmed time and the other confirmed
  interviewers are untouched unless the pool's exhausted for that seat,
  which escalates exactly like Module 6's exhausted-pool case.

**Edge cases**: a cancel/decline arriving after the interview's already
happened (check `Interview.status`/`confirmed_start_utc` against now before
acting). Two different confirmed interviewers cancelling their seats at
nearly the same moment (each should independently trigger its own seat's
cascade — verify one cancellation's cascade doesn't accidentally interfere
with the other seat's state).

---

## Shared: Notification Service

Build this once, use it from Modules 2 (invite email), 6 (offer
accept/decline links), 7 (confirmation + `.ics`), and 8 (reminders,
cancellation notices) — don't reimplement email sending four times.

**Suggested shape**: `app/notifications/service.py` with a single
`send_email(to: str, subject: str, body_html: str, ics_attachment: bytes | None = None)`.
Internally, either:
- Route through the sending user's own Gmail (`gmail.send` scope, already
  requested at login — use `get_valid_access_token`), or
- Use an external provider (SendGrid/Resend) with its own API key in `.env`.

**Decide and document which** in [ARCHITECTURE.md](ARCHITECTURE.md) — it
changes whether email arrives from a real person's Gmail address versus a
service address, and whether it's another `.env` entry to manage.

**Signed action links** (offer accept/decline, interviewer-initiated cancel):
generalize the pattern already used for `InviteToken` — hash-and-store-only,
single-use, expiring. Don't build a separate ad hoc token scheme per module.
