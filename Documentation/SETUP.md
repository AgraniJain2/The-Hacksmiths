# Local Setup

Full command-by-command setup (venv, install, migrate, run) lives in
[`backend/README.md`](../backend/README.md) — this page is the context around
it: what you need before those commands work, and where to get it.

## 1. Get added to Google Cloud Console

The project already has a GCP project + OAuth client set up. Ask whoever set
it up (check with the team) to add your Google account under:

**GCP Console → APIs & Services → OAuth consent screen → Test users**

Without this, Google blocks your login attempt with "access blocked: app has
not completed verification" — the app is intentionally kept in Testing mode
to avoid Google's multi-day verification review, which means only listed test
accounts can use it at all.

## 2. Get `.env` values

`backend/.env` is gitignored and holds real secrets — it is **not** shared via
chat or committed. Ask a teammate to share the file directly (or its values
through a private channel), or if you're setting up your own separate GCP
project for isolated testing, see the "Google Cloud Console setup" section
that was used originally (ask in the team channel for the walkthrough) and
fill in `backend/.env.example`'s template yourself.

If you're listed in `ALLOWED_INTERNAL_USERS` already, you don't need your own
GCP project — the shared one works for you.

## 3. Run it

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
alembic upgrade head            # applies existing migrations — don't autogenerate unless you've changed models.py
uvicorn app.main:app --reload --port 8000
```

Then confirm it's alive: `http://localhost:8000/health` should return
`{"status": "ok"}`.

## 4. Confirm your login works

Open `http://localhost:8000/auth/google/login` in a browser signed in with
your test-user Google account. After consenting, you'll land on
`http://localhost:5173/auth/complete` — that page doesn't exist yet (no
frontend built), so the browser will show a connection error there. That's
expected. From the same browser tab, go to `http://localhost:8000/auth/me` —
if that returns your email/role/granted scopes, you're set up correctly.

If anything fails here, check [AUTH_MODULE.md](AUTH_MODULE.md#known-gotchas-dont-rediscover-these)
first — the most common issues (scope-mismatch errors, cookie not being set,
"access blocked") are all documented there with the fix.
