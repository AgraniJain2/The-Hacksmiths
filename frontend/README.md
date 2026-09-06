# WorkHire — Frontend

React 18 + Vite (plain JS/JSX, no TypeScript) + React Router. Implements the
pages that only depend on the auth module (Module 1): Login, the OAuth
callback landing page, an authenticated dashboard shell, and Google
connection management. Every later module's UI should be built on top of the
same design system — read
[`Documentation/FRONTEND_DESIGN_SYSTEM.md`](../Documentation/FRONTEND_DESIGN_SYSTEM.md)
at the repo root before adding a page.

## Setup

```bash
cd frontend
npm install
copy .env.example .env      # Windows; `cp` on macOS/Linux — default is fine for local dev
npm run dev
```

Requires the backend running at the URL in `.env` (`VITE_API_BASE_URL`,
default `http://localhost:8000`) with `FRONTEND_URL=http://localhost:5173` in
`backend/.env` — the OAuth redirect and CORS both depend on that matching.

## What's here

| Route | Page | Needs auth? |
|---|---|---|
| `/login` | Sign-in screen. Reads `?invite_token=` for candidate invite links and forwards it to `GET /auth/google/login`. | no |
| `/auth/complete` | Where Google's OAuth redirect lands after `/auth/google/callback` sets the session cookie. Confirms the session via `GET /auth/me`, then routes into the app. | the redirect itself sets the cookie |
| `/dashboard` | Authenticated home: profile summary, Google connection summary, roadmap of not-yet-built modules. | yes |
| `/settings/google` | Full Google connection management — granted scopes, connect/reconnect/disconnect. | yes |

`/` redirects to `/dashboard` (which bounces to `/login` if not authenticated).
Anything unmatched renders a themed 404.

## Structure

```
src/
  lib/api.js            — the only place that calls the backend (fetch wrapper, credentials included)
  context/               — ThemeContext (light/dark), AuthContext (current user)
  components/            — shared building blocks: AppShell, ThemeToggle, GoogleConnectionCard, icons, etc.
  pages/                 — one folder-less pair per route: Foo.jsx + Foo.module.css
  styles/tokens.css       — design tokens (colors, type, spacing) — see the design system doc
  styles/global.css       — reset + shared utility classes (.btn, .glass-card, .pill, ...)
```

## Notes for whoever builds the next module's UI

- Don't `fetch()` directly in a component — add a function to `src/lib/api.js`
  and call that, same reasoning as the backend's "all config through
  `config.py`" rule: one place to see every backend call.
- Wrap any new authenticated page in the existing `AppShell` layout route in
  `App.jsx` rather than rebuilding a nav/header.
- Errors from the backend arrive as `{ detail, reason? }`; `api.js` throws an
  `Error` with `.status`, `.detail`, `.reason` set — branch on `.detail`
  (`google_not_connected`, `google_scope_missing:<scope>`, `reauth_required`)
  the same way the backend's own conventions expect the frontend to, per
  [AUTH_MODULE.md](../Documentation/AUTH_MODULE.md#3-get-a-live-google-access-token-to-actually-call-calendargmail).
- Known gap: if `resolve_role_on_first_login` rejects a login (bad/expired
  invite, not on `ALLOWED_INTERNAL_USERS`), the backend currently raises an
  HTTPException *during* `/auth/google/callback`, which the browser hits
  directly after Google's redirect — so the user sees a raw JSON error
  instead of landing back on `/login` with a friendly message. Worth a
  backend follow-up (redirect to `FRONTEND_URL/login?error=...` instead of
  raising) but out of scope for this pass since it touches the auth module.
