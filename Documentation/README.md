# Smart Interview Scheduler — Documentation

Index for everyone on the team (and your AI coding agents) to get oriented without
having to ask what's already built. Read this file first, then jump to whatever's
relevant to your piece.

## What this project is

An automated interview-scheduling platform: a recruiter creates an interview
request, the system checks everyone's real Google Calendar, works out a slot
that fits candidate + panel + working hours + buffers, gets it picked/confirmed,
books it (calendar event + Meet link), and handles the fallout when someone
declines or needs to reschedule. Full problem statement context lives in the
team's chat history / original PDF — this folder documents **what we've actually
decided and built**, not the raw brief.

## Current status (update this as modules land)

| Module | Status | Doc |
|---|---|---|
| Auth (Google OAuth, sessions, RBAC) | ✅ Built & working | [AUTH_MODULE.md](AUTH_MODULE.md) |
| Interview Request creation | 🔲 Not started | [MODULE_GUIDE.md](MODULE_GUIDE.md#module-2--interview-request) |
| Interviewer Pool Profile | 🔲 Not started | [MODULE_GUIDE.md](MODULE_GUIDE.md#module-2b--interviewer-pool-profile) |
| Candidate Availability Collection | 🔲 Not started | [MODULE_GUIDE.md](MODULE_GUIDE.md#module-3--candidate-availability-collection) |
| Interviewer Pool Feasibility Check | 🔲 Not started | [MODULE_GUIDE.md](MODULE_GUIDE.md#module-4--interviewer-pool-feasibility-check) |
| Candidate Slot Selection | 🔲 Not started | [MODULE_GUIDE.md](MODULE_GUIDE.md#module-5--candidate-slot-selection) |
| Interviewer Assignment & Cascade (load-balanced, sequential) | 🔲 Not started | [MODULE_GUIDE.md](MODULE_GUIDE.md#module-6--interviewer-assignment--cascade) |
| Event Creation & Dispatch (Meet link, emails, .ics) | 🔲 Not started | [MODULE_GUIDE.md](MODULE_GUIDE.md#module-7--event-creation--dispatch) |
| Post-Booking Exception Handling (reminders, cancel/reschedule both parties) | 🔲 Not started | [MODULE_GUIDE.md](MODULE_GUIDE.md#module-8--post-booking--exception-handling) |
| Notification Service (shared) | 🔲 Not started | [MODULE_GUIDE.md](MODULE_GUIDE.md#shared-notification-service) |
| Frontend | 🔲 Not started | — |

## Doc map

- **[WORKFLOW.md](WORKFLOW.md)** — the end-to-end flow we agreed on (7 stages), with the
  open questions we resolved and why. Read this before touching any module — it's
  the contract everyone's building against.
- **[ARCHITECTURE.md](ARCHITECTURE.md)** — tech stack, why we picked it, and the
  trade-off answers for "why this over X" / "what breaks at scale" (you'll be asked
  these in evaluation — know the answers for your module).
- **[AUTH_MODULE.md](AUTH_MODULE.md)** — what's built, how to call into it from your
  module (`get_current_user`, `require_google_scope`, `get_valid_access_token`),
  and gotchas that cost us real debugging time (keep future agents from repeating them).
- **[DATA_MODEL.md](DATA_MODEL.md)** — every table that exists today, how they relate,
  and the Alembic workflow for adding your own.
- **[MODULE_GUIDE.md](MODULE_GUIDE.md)** — one section per remaining module: goal,
  what it depends on, suggested endpoints/models, and exactly which existing
  function to call for Google access. **This is the file to hand your AI agent**
  when you start on a module — it has the integration contract, not just the idea.
- **[CONVENTIONS.md](CONVENTIONS.md)** — rules everyone's code needs to follow
  (secrets, error handling, RBAC pattern) — these map directly to hackathon
  evaluation criteria, not just style preference.

## Repo layout

```
backend/
  app/
    core/      — config (env vars) + security (encryption, JWT, signed state)
    db/        — SQLAlchemy models + session/engine setup
    auth/      — the built auth module (see AUTH_MODULE.md)
    main.py    — FastAPI app entrypoint
  alembic/     — DB migrations
  requirements.txt
  .env         — real secrets, gitignored, ask a teammate for values (never re-share in chat)
  .env.example — the template, safe to commit
Documentation/ — you are here
workflow.txt   — original ASCII workflow diagram (superseded by WORKFLOW.md, kept for history)
```

## Ground rules that apply to every module (from the hackathon guidelines)

- No hardcoded secrets, ever — config only through `app/core/config.py` reading
  `.env`. Committing a real key is an instant fail on this hackathon's rubric.
- Every new user-facing feature needs to say what role can do it (RBAC) — see
  the pattern in [AUTH_MODULE.md](AUTH_MODULE.md#using-auth-from-your-module).
- Write defensive code: empty inputs, missing calendars, expired tokens, and
  double-clicks are things evaluators will actually try.
- Whatever AI tool/agent you use to build your module, log what you used it for
  in the root `README.md` (not this folder) — that's a mandatory, graded
  disclosure for the hackathon, separate from this technical documentation.
