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
what they used AI for here.

- **Auth module (backend)**: built with Claude — Google OAuth flow, session
  JWTs, encrypted token storage, RBAC role resolution. Designed manually:
  the invite-token-vs-allowlist authorization model and which edge cases to
  guard.
- **Frontend — Setup & Auth pages + design system**: built with Claude —
  the React/Vite scaffold, the WorkHire design system (tokens, theming,
  shared components), and the Login / auth-callback / dashboard / Google
  connection pages, all wired to the existing auth-module API. Designed
  manually: which pages were buildable now vs. blocked on unbuilt backend
  modules, and the page/routing structure future modules should extend.
