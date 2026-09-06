# Backend — Smart Interview Scheduler

FastAPI + SQLAlchemy + Alembic. Currently implements the **Google OAuth
authentication module** (see `app/auth/`); the scheduling logic and Calendar/
Gmail/Meet integrations build on top of `google_oauth.get_valid_access_token()`.

## Setup

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt

copy .env.example .env          # then fill in the values (see repo root chat/README for how to get them)

alembic revision --autogenerate -m "init auth tables"
alembic upgrade head

uvicorn app.main:app --reload --port 8000
```

## Auth flow quick test

1. Internal user: open `http://localhost:8000/auth/google/login` in a browser signed
   in with an account listed in `ALLOWED_INTERNAL_USERS` — you'll get exactly the
   role configured for that email (recruiter/hiring_manager/interviewer).
2. Candidate: needs `?invite_token=...` appended — invite tokens are minted by the
   Interview module (not yet built) via `InviteToken` + `hash_invite_token()`.
3. After consent, you land on `FRONTEND_URL/auth/complete` with a `session` cookie set.
4. `GET /auth/me` (with cookies) returns the current user + which Google scopes were
   actually granted.
5. `POST /auth/google/disconnect` revokes Google access without logging out of the app.

## Where things live

- `app/core/config.py` — all env-driven settings.
- `app/core/security.py` — token encryption, session JWTs, signed OAuth state.
- `app/db/models.py` — `User`, `OAuthToken`, plus `Interview`/`InviteToken` stubs.
- `app/auth/google_oauth.py` — the only module that talks to Google's OAuth endpoints.
- `app/auth/dependencies.py` — `get_current_user`, `require_google_scope(...)`.
- `app/auth/router.py` — `/auth/google/login|callback|disconnect`, `/auth/me|logout`.
