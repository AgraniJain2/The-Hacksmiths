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

See [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) for the actively-maintained,
phase-by-phase version of this table (what's shipped, what's next, in what
order) — this one is the coarse per-module summary.

| Module | Status | Doc |
|---|---|---|
| Auth (Google OAuth, sessions, RBAC) | ✅ Built & working | [AUTH_MODULE.md](AUTH_MODULE.md) |
| Interview Request creation | ✅ Built — real DB persistence (Phase 2) | [MODULE_GUIDE.md](MODULE_GUIDE.md#module-2--interview-request) |
| Interviewer Pool Profile | ✅ Built — real DB persistence (Phase 2) | [MODULE_GUIDE.md](MODULE_GUIDE.md#module-2b--interviewer-pool-profile) |
| Candidate Availability Collection | ✅ Built — real DB persistence (Phase 2) | [MODULE_GUIDE.md](MODULE_GUIDE.md#module-3--candidate-availability-collection) |
| Interviewer Pool Feasibility Check | ✅ Built — real Google Calendar check (Phase 3), verified against real accounts | [MODULE_GUIDE.md](MODULE_GUIDE.md#module-4--interviewer-pool-feasibility-check) |
| Candidate Slot Selection | ✅ Built — real DB persistence (Phase 2) | [MODULE_GUIDE.md](MODULE_GUIDE.md#module-5--candidate-slot-selection) |
| N-Seat Interviewer Assignment (load-balanced, per-seat cascade) | ✅ Built — real DB persistence + a real per-interviewer lock (Phase 2) + real Calendar re-check at fixed time (Phase 3) | [MODULE_GUIDE.md](MODULE_GUIDE.md#module-6--n-seat-interviewer-assignment) |
| Event Creation & Dispatch (Meet link, emails, .ics) | ✅ Built (Phase 4) — real Calendar event + Meet link, verified against real accounts | [MODULE_GUIDE.md](MODULE_GUIDE.md#module-7--event-creation--dispatch) |
| Post-Booking Exception Handling (reminders, cancel/reschedule both parties) | 🟡 Cancel/reschedule built; reminders + offer-expiry sweep not started (Phase 5) | [MODULE_GUIDE.md](MODULE_GUIDE.md#module-8--post-booking--exception-handling) |
| Notification Service (shared) | ✅ Built — real email via Resend (Phase 1) | [MODULE_GUIDE.md](MODULE_GUIDE.md#shared-notification-service) |
| Frontend — Setup & Auth pages (login, callback, dashboard shell, Google connection) | ✅ Built | [FRONTEND_DESIGN_SYSTEM.md](FRONTEND_DESIGN_SYSTEM.md) |
| Frontend — remaining pages (one per module above) | ✅ Built (all wired to the real DB-backed API now) | [FRONTEND_DESIGN_SYSTEM.md](FRONTEND_DESIGN_SYSTEM.md#adding-a-new-authenticated-page) |

## Doc map

- **[WORKFLOW.md](WORKFLOW.md)** — the end-to-end flow we agreed on (8 stages), with the
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
- **[FRONTEND_DESIGN_SYSTEM.md](FRONTEND_DESIGN_SYSTEM.md)** — the frontend's
  design tokens, theming (light/dark), shared components/layout, routing and
  API-client conventions. **Read this before building any new page** — it's
  the frontend equivalent of `MODULE_GUIDE.md` + `CONVENTIONS.md` combined.

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
frontend/
  src/
    lib/api.js     — the only file that calls the backend
    context/       — ThemeContext (light/dark), AuthContext (current user)
    components/    — shared building blocks (AppShell, ThemeToggle, GoogleConnectionCard, icons, ...)
    pages/         — one route each (Login, AuthComplete, Dashboard, GoogleConnection, ...)
    styles/        — tokens.css (design tokens) + global.css (shared utility classes)
  see FRONTEND_DESIGN_SYSTEM.md for the full design system
Documentation/ — you are here
workflow.txt   — quick-glance ASCII mirror of WORKFLOW.md's stages (WORKFLOW.md is the maintained source of truth)
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
