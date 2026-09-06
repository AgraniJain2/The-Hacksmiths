# Auth Module — What's Built & How to Use It

Status: **built and verified working** (real Google login tested end-to-end
against a live Google account — see the "Verified working" note at the bottom).

This is the one module every other module depends on. Read the "Using auth
from your module" section before writing any code that needs a user's
identity or their Calendar/Gmail access.

## What it does

Every user type — recruiter, hiring manager, interviewer, **and candidate** —
signs in with Google. That single decision (documented in
[WORKFLOW.md](WORKFLOW.md)) is why the module is more involved than a typical
"login with Google" button: it also has to decide who's even allowed to have
an account, since there's no company email domain to gate on.

**Role assignment** (`resolve_role_on_first_login` in `backend/app/auth/router.py`):
- A candidate authenticates via a **signed, single-use invite link**
  (`?invite_token=...`) tied to one specific `Interview` row and one email
  address. No invite token → no candidate account.
- Internal staff (recruiter/hiring_manager/interviewer) are listed explicitly
  in the `ALLOWED_INTERNAL_USERS` env var as `email:role` pairs — because
  everyone's using personal Gmail, not a shared domain. Not on the list, no
  invite token → login is rejected outright (`signup_not_allowed`).

**Token handling**: Google's Authorization Code flow with
`access_type=offline&prompt=consent`, so we get a refresh token, not just a
short-lived access token — required because the scheduler needs to check
calendars and send reminders long after the user has closed the browser tab.
Both access and refresh tokens are **AES-GCM encrypted at rest** — never
stored or logged in plaintext.

## Endpoints

| Method & path | Purpose | Auth required |
|---|---|---|
| `GET /auth/google/login?invite_token=` | Redirects to Google consent. `invite_token` only for candidates. | none |
| `GET /auth/google/callback` | Google redirects here with `code`+`state`. Creates/loads the user, stores encrypted tokens, sets the session cookie, redirects to `FRONTEND_URL/auth/complete`. | none (this *is* the login) |
| `GET /auth/me` | Current user's id/email/name/role + which Google scopes were actually granted. | session cookie |
| `POST /auth/logout` | Clears the session cookie. Does not touch Google's grant. | session cookie |
| `POST /auth/google/disconnect` | Revokes the Google grant and deletes stored tokens. User stays logged into the app, just loses Calendar/Gmail access. | session cookie |

## Data model

See [DATA_MODEL.md](DATA_MODEL.md) for full column listings. Summary:
- `User` — one row per person, `role` is one of `candidate | recruiter | hiring_manager | interviewer`.
- `OAuthToken` — one row per user, encrypted access/refresh tokens + the scope string actually granted + expiry.
- `Interview` — started as a minimal stub the auth module needed for the
  candidate invite flow; the scheduling module (`app/scheduling/service.py`)
  now owns it as the full table DATA_MODEL.md describes — don't create a
  second interviews table.
- `InviteToken` — still exactly what it was: a signed, single-use invite
  letting a candidate authenticate against one specific interview.

## Using auth from your module

Three things you'll import from `app.auth`:

**1. Require a logged-in user, get their role:**
```python
from fastapi import Depends
from app.auth.dependencies import get_current_user
from app.db.models import User

@router.post("/interviews")
def create_interview(payload: ..., user: User = Depends(get_current_user)):
    if user.role != "recruiter":
        raise HTTPException(status_code=403, detail="recruiter_only")
    ...
```

**2. Require a specific Google scope before letting a route run** (fails fast
with a specific reason instead of crashing deep inside a Calendar/Gmail call):
```python
from app.auth.dependencies import require_google_scope

@router.post("/interviews/{id}/book", dependencies=[Depends(require_google_scope("calendar"))])
def book_slot(...):
    ...
```
This returns `403 {"detail": "google_not_connected"}` or
`403 {"detail": "google_scope_missing:calendar"}` — your frontend should
handle both by prompting the user to (re)connect Google, not as a generic error.

**3. Get a live Google access token to actually call Calendar/Gmail** — this
is the *only* correct way to get a token; never read `OAuthToken` rows
yourself or decrypt them outside `app/auth/google_oauth.py`:
```python
from app.auth.google_oauth import get_valid_access_token, ReauthRequired
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials

def check_freebusy(db, user_id: str, ...):
    access_token = get_valid_access_token(db, user_id)  # refreshes if needed
    creds = Credentials(token=access_token)
    service = build("calendar", "v3", credentials=creds)
    return service.freebusy().query(body={...}).execute()
```
If the user's Google connection is dead (revoked, refresh failed),
`get_valid_access_token` raises `ReauthRequired` — there's already a global
FastAPI exception handler in `app/main.py` that turns this into a clean
`401 {"detail": "reauth_required", "reason": "..."}`. You don't need to catch
it yourself unless you want to do something extra.

## Known gotchas (don't rediscover these)

- **`OAUTHLIB_RELAX_TOKEN_SCOPE`**: Google rewrites the `profile`/`email`
  scope aliases to their full `.../auth/userinfo.*` URLs in the token
  response. The underlying `oauthlib` library treats that as a scope mismatch
  and raises by default. Already patched in `app/auth/google_oauth.py` — if
  you see a `Warning: Scope has changed from ...` traceback, you're bypassing
  that module and calling oauthlib directly; don't.
- **GCP OAuth consent screen must stay in "Testing" mode** for the hackathon
  (avoids Google's multi-day verification review). That means **every Google
  account you test or demo with must be added under OAuth consent screen →
  Test users** in Google Cloud Console, or login fails with "access blocked."
- **`SESSION_COOKIE_SECURE=false`** is required for local `http://localhost`
  dev — secure cookies are silently dropped by browsers over plain HTTP. Flip
  it to `true` the moment this is served over HTTPS anywhere.
- **The frontend doesn't exist yet.** After a real login, the callback
  redirects to `FRONTEND_URL/auth/complete`, which currently 404s/connection-
  errors in the browser — that's expected. The session cookie is already set
  by that point; test with `GET /auth/me` from the same browser instead of
  trusting what the redirect page shows.
- **Google tokens never leave the backend.** The frontend only ever sees our
  own session cookie. If you find yourself wanting to pass an access/refresh
  token to the frontend "just to make an API call easier" — don't; add a
  backend endpoint that makes the Google call server-side instead.

## Verified working

Manually tested end-to-end: real Google account → consent screen → callback
→ user created with correct role from `ALLOWED_INTERNAL_USERS` → tokens
stored encrypted → `/auth/me` returned correct email/role/granted scopes.
