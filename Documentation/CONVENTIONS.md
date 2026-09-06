# Conventions

These map directly to the hackathon's evaluation guidelines — not just style
preference. Following them keeps every module consistent enough that a
teammate (or their AI agent) can read your code without relearning your
personal patterns, and keeps us from failing an evaluation criterion by accident.

## Secrets — no exceptions

- All config through `app/core/config.py` (`Settings`, reading `.env`). Never
  `os.environ.get(...)` scattered through feature code, and never a literal
  API key/token/password in any `.py` file.
- **Hardcoding a secret and committing it is an automatic hackathon fail**
  (explicitly called out in the guidelines). `.env` is gitignored — keep it
  that way, and never paste real secret values into chat, PR descriptions, or
  commit messages.
- New secret needed for your module (an email provider key, an SMS provider
  key, etc.)? Add the variable to `Settings` in `config.py` *and* to
  `backend/.env.example` with a comment on where to get it — don't just add it
  to your local `.env` and leave everyone else's setup broken.

## RBAC pattern

Every endpoint that isn't public (`login`, `callback`) should declare who can
call it, using the pattern already in `app/auth/dependencies.py`:

```python
def create_interview(payload: ..., user: User = Depends(get_current_user)):
    if user.role not in ("recruiter", "hiring_manager"):
        raise HTTPException(status_code=403, detail="insufficient_role")
```

For anything needing Calendar/Gmail access, stack `require_google_scope(...)`
on top (see [AUTH_MODULE.md](AUTH_MODULE.md#using-auth-from-your-module)) — a
missing scope should never surface as a raw exception from inside a Google
API call.

## Error handling

- Prefer specific, typed errors over generic 500s — the pattern to follow is
  `ReauthRequired` in `app/auth/google_oauth.py`: a real exception class with
  a `reason`, caught by a global handler in `main.py`, turned into a
  consistent JSON shape the frontend can branch on.
- Every endpoint that takes user input should handle: empty/missing fields,
  wrong types, and (where relevant) double-submission — evaluators are
  explicitly going to try empty fields, invalid uploads, and rapid clicking.
- Don't let one failure silently produce a wrong-but-plausible result (e.g. a
  broken calendar connection for one panelist making the availability
  calculator think everyone's free) — fail loud and specific.

## Database changes

- Add tables/columns in `app/db/models.py`, then
  `alembic revision --autogenerate -m "..."` — see
  [DATA_MODEL.md](DATA_MODEL.md#migrations). Don't hand-edit a migration
  that's already been applied by someone else; add a new one.
- Extend the existing `Interview` stub rather than creating a second
  interviews table — check [DATA_MODEL.md](DATA_MODEL.md) before adding a
  table in case something close already exists.

## Logging

- Never log a token (access, refresh, or invite), full request bodies
  containing them, or anything from `OAuthToken`. Log user ids/emails and
  action names, not secrets.

## AI usage disclosure (hackathon-mandatory, not optional)

Whatever AI tool or agent you use to build your module, add a line to the
**root** `README.md` (not this Documentation folder) describing what you used
it for, e.g. "Generated the Calendar freebusy integration using Claude;
designed the slot-ranking algorithm and edge cases manually." Be ready to
explain and defend any AI-generated logic in the code walkthrough — "the AI
wrote it" is not an acceptable answer to "why does this work this way."

## Commit hygiene

- Branch off `main` per module/feature rather than committing directly to
  `main`, so a broken module doesn't block everyone else's work at demo time.
- Keep `Documentation/` up to date as modules land — flip the status table in
  [README.md](README.md) when your module is working, and add/update the
  relevant doc file. A stale doc is worse than no doc because people will
  trust it.
