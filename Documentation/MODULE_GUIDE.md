# Module Guide — Pick One, Hand This to Your AI Agent

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

**Goal**: recruiter creates an interview request — the thing every later
stage operates on. No named panelist, no panelist count — just requirements.

**Depends on**: `get_current_user` (only recruiters/hiring_managers should be
able to create one — check `user.role`), the `Interview` stub in
`app/db/models.py`.

**Build**:
- Extend `Interview` per [DATA_MODEL.md](DATA_MODEL.md#interview-extend-the-existing-stub):
  `interview_type`, `required_skills`, `required_seniority`,
  `hiring_manager_id`, candidate email/timezone, duration/buffer, the new
  `status` enum.
- `POST /interviews` — create one (recruiter/hiring_manager only). Validates
  `required_skills` is non-empty, `duration_minutes > 0`, candidate email is
  well-formed.
- `GET /interviews/{id}` — fetch details + current status.
- On creation, mint an `InviteToken` (see [DATA_MODEL.md](DATA_MODEL.md#invitetoken-existing-unchanged))
  for the candidate and hand it to the Notification Service to email — this
  is the link the candidate uses to log in and eventually pick a slot.

**Edge cases**: empty/malformed candidate email, zero-length `required_skills`,
duration of 0 or negative, `required_seniority` not matching any active
interviewer at all (arguably should warn the recruiter at creation time
rather than only failing silently later in Stage 4).

---

## Module 2B — Interviewer Pool Profile

**Goal**: let interviewers declare what they're qualified for, and toggle
whether they're currently available to be assigned.

**Depends on**: `get_current_user` with `role == "interviewer"`.

**Build**:
- `InterviewerProfile` table, per [DATA_MODEL.md](DATA_MODEL.md#interviewerprofile-new--module-2b).
- `PUT /me/interviewer-profile` — upsert your own skills/seniority/qualified
  types/active flag. Interviewer-only.
- `GET /me/interviewer-profile` — read your own.
- Consider whether profile edits need approval (e.g., can anyone self-declare
  `STAFF` seniority?) — simplest for hackathon scope: self-declared, no
  approval workflow, flagged here as a known simplification if asked about
  it in the walkthrough.

**Edge cases**: an interviewer with `role == "interviewer"` who never creates
a profile (should be treated as inactive/ineligible everywhere, not crash
Module 4/6's queries — a plain `LEFT JOIN`/optional lookup, not an assumed row).

---

## Module 3 — Candidate Availability Collection

**Goal**: candidate (already logged in via their invite link) submits the
time windows they're free.

**Depends on**: candidate login already works (built — see
[AUTH_MODULE.md](AUTH_MODULE.md)); a candidate hitting
`/auth/google/login?invite_token=...` already gets a session with
`role=candidate`.

**Build**:
- `CandidateAvailabilityWindow` table, per [DATA_MODEL.md](DATA_MODEL.md#candidateavailabilitywindow-new--module-3).
- `POST /interviews/{id}/availability` — candidate-role-only, submits one or
  more `{start, end}` windows in their own timezone (candidate should
  explicitly confirm/select their timezone — never infer it silently from
  browser locale or IP, per the earlier timezone-handling decision).
- Update `Interview.status` to `collecting_availability` →
  `awaiting_candidate_selection` once at least one window is submitted and
  Module 4 has produced feasible slots.

**Edge cases**: overlapping submitted windows (dedupe/merge them), a window
shorter than `duration_minutes + buffer_minutes` (not usable — filter it out
rather than passing it through to Module 4 as if it were valid), candidate
resubmitting availability after already picking a slot (should this replace
prior windows or append? default to replace, since re-submission implies the
old ones are stale).

---

## Module 4 — Interviewer Pool Feasibility Check

**Goal**: given an interview's requirements and the candidate's submitted
windows, return which windows have *at least one* eligible, calendar-free
interviewer — not a ranked list, just feasible/not.

**Depends on**: `get_valid_access_token(db, user_id)` from
`app.auth.google_oauth` — this is the *only* way to get a usable Google
access token; never touch `OAuthToken` rows directly. Also depends on
Module 2B's `InterviewerProfile` data and Module 3's availability windows.

**Build**:
- Query eligible interviewers: `InterviewerProfile.active = true`,
  `required_seniority` satisfied, `interview_type` in
  `qualified_interview_types`, skills overlap with `required_skills`
  (decide subset-match vs. any-overlap-match — subset is stricter and
  probably right: an interviewer needs *all* required skills, not just one).
- For each eligible interviewer, call Calendar `freebusy.query` (via
  `get_valid_access_token`) and check against each of the candidate's
  submitted windows, minus `buffer_minutes` around existing events.
- Return the subset of candidate windows where the eligible set is non-empty.
  No ranking needed here — Module 6 does the ranking, and only once a
  specific time is fixed.
- **Explicit "no feasible slot" response** if the eligible set is empty for
  every window — surface which constraint is the blocker (no active
  interviewers with this skill set at all vs. everyone's just busy) so the
  recruiter/candidate knows what to fix.

**Edge cases**: an eligible interviewer with a dead Google connection
(`ReauthRequired`) — don't let one broken connection silently exclude them
from every slot forever without at least logging/surfacing that they need to
reconnect. DST transitions — store/compare everything in UTC.

---

## Module 5 — Candidate Slot Selection

**Goal**: candidate picks one exact time from Module 4's feasible list.

**Depends on**: Module 4's output.

**Build**:
- `GET /interviews/{id}/slots` — candidate-role-only, returns the feasible
  windows converted to the candidate's timezone.
- `POST /interviews/{id}/slots/select` — candidate picks one exact
  `{start, end}`; sets `Interview.status = assigning_interviewer` and hands
  off to Module 6.

**Edge cases**: idempotency (candidate double-clicking submit shouldn't
trigger two separate Module 6 assignment attempts — check current
`Interview.status` before proceeding), the picked slot no longer being
feasible by the time they submit (re-validate against Module 4's logic at
selection time, don't trust a stale client-side list).

---

## Module 6 — Interviewer Assignment & Cascade

**Goal**: the core new logic. Given the interview's now-fixed time, pick one
interviewer deterministically, notify them, and cascade to the next on
decline/timeout.

**Depends on**: `get_valid_access_token`, `InterviewerProfile`, the
`InterviewSlotOffer` table, and the Notification Service (see below).

**Build**:
1. **Ranking function**: eligible-and-free-at-the-fixed-time interviewers
   (same filter as Module 4, re-checked live), ordered by the two computed
   queries in [DATA_MODEL.md](DATA_MODEL.md#interviewerprofile-new--module-2b)
   — lowest rolling 7-day confirmed count first, least-recently-assigned as
   tiebreak.
2. **Offer creation** (used both for the first attempt and every cascade
   step): in one transaction, lock the target interviewer's
   `InterviewerProfile` row, re-verify no overlapping `OFFERED` or confirmed
   `InterviewParticipant` exists for them, insert the `InterviewSlotOffer`
   row (`status=OFFERED`, `expires_at` = now + your chosen timeout, e.g. 2
   hours), then have the Notification Service send them the
   accept/decline links (signed, single-use, same pattern as `InviteToken` —
   reuse `hash_invite_token`-style hashing rather than inventing a new scheme).
3. **`POST /offers/{id}/accept`** (via the signed link, no login required —
   the signed token *is* the auth) — inside a transaction: verify the offer
   is still `OFFERED` and not expired, mark it `ACCEPTED`, create the
   `InterviewParticipant` row, set
   `Interview.assigned_interviewer_id` + `status = scheduled`, then hand off
   to Module 7.
4. **`POST /offers/{id}/decline`** and the **expiry sweep** (a scheduled job,
   same infra as Module 8's reminders, checking for `OFFERED` rows past
   `expires_at`) both do the same thing: mark the offer `DECLINED`/`EXPIRED`,
   re-run the ranking excluding everyone already offered this interview, and
   either create the next offer or, if the ranked list is now empty, set
   `Interview.status = needs_recruiter_action` and notify the recruiter.

**Edge cases**: the interviewer who declines is the *only* eligible one
(immediate escalation, no cascade possible) — test this path explicitly,
it's the one evaluators are likely to probe ("what happens when nobody's
available?"). An `accept`/`decline` link clicked twice (idempotent: second
click on an already-`ACCEPTED`/`DECLINED` offer should return a clear
"already handled" message, not double-book or crash).

---

## Module 7 — Event Creation & Dispatch

**Goal**: once Module 6 lands an acceptance, create the real calendar event
(with Meet link) and notify everyone.

**Depends on**: `get_valid_access_token` (use the **recruiter's or an
organizer's** token to create the event, with the candidate + assigned
interviewer + hiring manager as attendees), the Notification Service.

**Build**:
- Calendar API `events.insert` with `conferenceData: {createRequest: {...}}`
  and `conferenceDataVersion=1` — this is how you get a real Google Meet link
  out of the Calendar API; there's no separate "create a Meet link" call.
- Store the returned event id on `Interview.calendar_event_id` and the Meet
  link on `Interview.meeting_link`.
- Send confirmation email to candidate + hiring manager + assigned
  interviewer via the Notification Service, with a `.ics` attachment as a
  fallback for anyone not on Google Calendar.

**Edge cases**: event creation succeeds but notification send fails (or vice
versa) — don't leave a booking where the calendar event exists but nobody
was told, or where people were told but no event exists; make these two
steps individually retryable/idempotent if you can (e.g., check
`calendar_event_id` is already set before creating a duplicate event on retry).

---

## Module 8 — Post-Booking & Exception Handling

**Goal**: reminders before the interview; both parties can cancel/reschedule,
each with a distinct downstream effect.

**Depends on**: Module 7's booking + calendar event, Module 6's cascade
logic (reused here), a scheduled job runner (a simple polling loop or a
library like APScheduler is enough for hackathon scope).

**Build**:
- A scheduled job finding bookings starting soon and sending reminders —
  same job can also run Module 6's offer-expiry sweep.
- `POST /interviews/{id}/cancel` (candidate) — release the assigned
  interviewer (flip their `InterviewParticipant.status` to `cancelled`,
  which automatically drops them from the live load-balancing count), notify
  them it's off, reset `Interview.status` back to `collecting_availability`.
- `POST /interviews/{id}/reschedule` (candidate) — same release as cancel,
  but expects new/updated availability windows and loops back to Module 3.
- `POST /interviews/{id}/interviewer-cancel` (assigned interviewer, via a
  signed link or authenticated session) — flip their `InterviewParticipant`
  to `cancelled`, then **re-run Module 6's ranking/cascade for the same fixed
  time**, excluding this interviewer. The candidate's confirmed time doesn't
  move unless the pool's exhausted, which escalates exactly like Module 6's
  exhausted-pool case.

**Edge cases**: a cancel/decline arriving after the interview's already
happened (check `Interview.status`/`confirmed_start_utc` against now before
acting — don't reschedule a completed interview). Both parties trying to
cancel at nearly the same moment (whichever transaction commits first wins;
the second should see the already-updated state and respond accordingly,
not error out).

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
changes whether email arrives from a real person's Gmail address (more
trustworthy-looking, but ties sending to that person's token being valid) or
a service address (more reliable, but is another API key to manage and
another `.env` entry to add for the whole team).

**Signed action links** (offer accept/decline, interviewer-initiated cancel):
generalize the pattern already used for `InviteToken` —
hash-and-store-only, single-use, expiring. Don't build a separate ad hoc
token scheme per module; if it's worth adding a shared `ActionToken` table
(token_hash, action_type, payload, expires_at, used_at) instead of one table
per link type, raise that as a small refactor once two modules need the same
shape, rather than deciding it upfront.
