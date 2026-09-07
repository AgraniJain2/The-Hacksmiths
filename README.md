# The-Hacksmiths — WorkHire

An automated interview-scheduling platform: a recruiter creates an interview
request, the system checks everyone's real Google Calendar, works out a slot
that fits candidate + panel + working hours + buffers, gets it
picked/confirmed, books it (calendar event + Meet link), and handles the
fallout when someone declines or needs to reschedule.

Full docs live in [`Documentation/`](Documentation/README.md) — start there.
Quick links: [WORKFLOW.md](Documentation/WORKFLOW.md) (the 8-stage flow),
[ARCHITECTURE.md](Documentation/ARCHITECTURE.md) (stack + trade-offs),
[FRONTEND_DESIGN_SYSTEM.md](Documentation/FRONTEND_DESIGN_SYSTEM.md) (UI
tokens/components/conventions).

## Running it locally

```bash
# Backend (FastAPI) — see backend/README.md for the full auth setup
cd backend
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env   # fill in Google OAuth + secrets
alembic upgrade head
uvicorn app.main:app --reload --port 8000

# Frontend (React + Vite) — in a second terminal
cd frontend
npm install
copy .env.example .env
npm run dev
```

Open `http://localhost:5173`.

## AI usage disclosure (hackathon-mandatory)

Per [CONVENTIONS.md](Documentation/CONVENTIONS.md), every contributor logs
what they used AI for here. The short version, upfront: **the team directed
this project; AI (Claude) was a tool the team pointed at well-specified
implementation work and then checked.** Every architectural call, every
acceptance decision, every "is this actually done" verdict, and the real
credentials behind every "verified for real, not mocked" claim in
[IMPLEMENTATION_PLAN.md](Documentation/IMPLEMENTATION_PLAN.md) came from a
human. Claude never decided what to build, only how to build what it was
told to, and its output was reviewed against human-written specs before it
counted as done. This breakdown is reconstructed from git history
(`git log --format="%an %s"`) and each phase's own record in
IMPLEMENTATION_PLAN.md, so it stays honest rather than a vague "AI helped
throughout."

### What the humans owned, end to end

- **The entire product design** — the 8-stage workflow
  ([WORKFLOW.md](Documentation/WORKFLOW.md)), the DB schema
  ([DATA_MODEL.md](Documentation/DATA_MODEL.md)), the stack/trade-off
  decisions ([ARCHITECTURE.md](Documentation/ARCHITECTURE.md)), and the
  N-interviewer requirements pass — decided and written by hand (Ujjwal)
  *before* any module, human- or AI-built, existed. This is the contract
  every later module (including every AI-built one) was built against, not
  something negotiated with or suggested by AI.
- **The scheduling algorithm itself** (Agrani) — the two-phase
  feasibility-then-ranking design, the interviewer-ranking tie-break rules,
  and the provider-ABC boundary in `backend/app/scheduling/` that every
  later module had to build against without touching. Hand-written, no AI
  tooling involved.
- **Backend project scaffolding** (Shamvrueth) — initial FastAPI + `uv`
  setup.
- **Every priority call, every phase's scope, and every "done" decision**
  for the six-phase build-out below — what shipped first (email before
  Calendar, persistence before hardening), what counted as finished, and
  which follow-ups (a live Postgres run, a signed passwordless email link)
  were deliberately deferred rather than missed.
- **Every piece of real-world proof** the AI's work had to pass — a human
  supplied the real Resend API key and verified sending domain and two real,
  personally-owned Google accounts, then reviewed the actual evidence
  (a restarted process reading back live state, a fetched Calendar event
  showing a working Meet link, a real `events().get()` confirming a
  cancellation actually deleted the event) before accepting any phase as
  real rather than mocked.
- **Catching AI's mistakes** — two concrete examples worth naming: Claude's
  first cut of the reservation lock in Phase 2 was provably racy under real
  concurrent load, and its first Calendar event payload in Phase 4 was
  silently rejected by Google's real API over a missing timezone field.
  Both only surfaced because a human insisted on real concurrency tests and
  a real API call instead of accepting AI's own confidence that the code
  was correct — Claude then fixed both, but under human-directed scrutiny,
  not on its own initiative.
- **The final say on security** — the `security-review` skill was run over
  the Phase 6 diff as one more assistant, not as the sign-off; a human
  decided the findings cleared the bar for the demo.

### What was delegated to AI (Claude), under human spec and review

- **Auth module (backend)**: Claude implemented the Google OAuth flow,
  session JWTs, encrypted token storage, and RBAC role resolution — to a
  human-designed spec (the invite-token-vs-allowlist authorization model and
  which edge cases to guard were decided by a human, not proposed by Claude).
- **Frontend — Setup & Auth pages + design system**: Claude implemented the
  React/Vite scaffold, the WorkHire design tokens/theming/shared components,
  and the Login / auth-callback / dashboard / Google-connection pages, wired
  to the already-built auth API. A human decided which pages were buildable
  yet vs. blocked on unbuilt backend modules, and the routing structure
  later modules had to extend.
- **Wiring the scheduling engine to HTTP + its frontend** (`scheduling/router.py`,
  `schemas.py`, the request/interviewer/candidate/notifications pages, and
  later moving the whole package into `backend/app/`): implemented by
  Claude, constrained by a human decision to leave the scheduling algorithm
  (Agrani's code) untouched and build only the thin router+store layer its
  own interfaces were designed for, and to reuse the existing candidate
  invite-link mechanism rather than let AI invent a second one.
- **Phases 0–6** — real DB persistence, real email via Resend, real Google
  Calendar free/busy checks, real Calendar event creation with a working
  Meet link + `.ics` invites, scheduled reminder/offer-expiry jobs,
  cancel/reschedule against the real event, and concurrency hardening:
  Claude wrote the implementation, one human-specified phase at a time, with
  every phase's goal, scope, and exit criteria set in advance and every
  result checked against real accounts before the next phase was allowed to
  start (see above).

### Bottom line

AI wrote a large share of the lines in `backend/app/` (outside the
scheduling algorithm) and in the frontend — but it wrote them against specs,
priorities, and acceptance bars a human set, and none of it shipped without
a human checking the real-world evidence first. The requirements, the
architecture, the scheduling algorithm, the phase plan, the credentials, and
the final "yes, this is actually done" call were never AI's to make. Any
AI-generated logic here should be treated as something the team can explain
and defend on its own terms, not a black box — see CONVENTIONS.md.
