# Frontend Design System — WorkHire

Read this before building any new page. It documents what exists in
`frontend/` today (Module 1 / auth pages) and the rules that keep every
future module's UI looking like the same product instead of four different
hackathon projects stitched together. Cross-read
[MODULE_GUIDE.md](MODULE_GUIDE.md) for what each remaining module needs to
build — this doc only covers *how it should look and be wired*, not what
each page does.

## Brand

- **Name**: WorkHire. Wordmark is set in `var(--font-display)` with "Hire"
  rendered in the accent gradient (`.text-gradient` in `global.css`) — see
  `src/components/Logo.jsx`. Don't re-typeset the name elsewhere; import
  `Logo`.
- **Vibe**: clean, futuristic, a little glassy — dark-first, but light mode
  is a fully designed peer, not an afterthought. Glass panels over a faint
  moving grid, gradient accents, generous whitespace, no visual clutter.
- **Favicon**: an inline data-URI SVG in `index.html` (the same mark as
  `Logo.jsx`) — no external asset to keep track of.

## Stack (and why)

| Choice | Reasoning |
|---|---|
| React 18 + Vite, **plain JS/JSX, no TypeScript** | Matches the hackathon's move-fast constraint; the auth-only surface built so far is small enough that TS's setup cost wasn't worth paying yet. If the codebase grows past ~Module 4, revisit this — don't let it rot as a permanent decision by default. |
| React Router v6 | Small, fixed route set (same reasoning ARCHITECTURE.md gives for REST over GraphQL on the backend) — a heavier routing/state framework would be solving a problem this app doesn't have. |
| **CSS Modules + a shared tokens/global stylesheet — no Tailwind, no component library** | Keeps the visual language in one place (`tokens.css`) that both the utility classes in `global.css` *and* every module's scoped styles read from, so "futuristic glass" stays consistent without a design-system package to install. Trade-off: more CSS to hand-write than Tailwind would need — acceptable at this scale, revisit if the page count grows a lot. |
| No icon library | ~10 icons total so far (`src/components/icons.jsx`). Pull one in (e.g. lucide) the moment hand-rolling SVGs stops being faster. |

Frontend is **not yet decided** in [ARCHITECTURE.md](ARCHITECTURE.md) prior
to this change — this doc plus that file's updated Frontend row are the
record of the decision now that it's made.

## Design tokens — `src/styles/tokens.css`

Every color, font, spacing, radius, and shadow used anywhere in the app is a
CSS custom property defined here. **Never hardcode a hex value, a raw `px`
spacing/radius, or a font name in a component's CSS** — add or reuse a token
instead. This is the single lever that keeps light/dark and future pages
consistent.

### Theming mechanism

- `ThemeContext` (`src/context/ThemeContext.jsx`) resolves the initial theme
  once — **stored choice (`localStorage["workhire-theme"]`) → OS
  `prefers-color-scheme` → `dark`** — and writes a concrete
  `data-theme="light"|"dark"` attribute onto `<html>`. There's no runtime
  "system" tri-state; the app always renders a definite theme.
- `tokens.css` defines light values on bare `:root` and overrides them under
  `:root[data-theme="dark"]` — never give a token its only definition inside
  the dark block.
- `ThemeToggle` (`src/components/ThemeToggle.jsx`) is a real switch
  (`role="switch"`, `aria-checked`) with a sliding thumb and sun/moon icons —
  not a plain icon button — per the brand's "toggle switch" requirement. It's
  already in `AppShell`'s nav; don't add a second one to an individual page.

### Token reference

| Group | Tokens | Notes |
|---|---|---|
| Type | `--font-display` (Space Grotesk, headings/brand), `--font-body` (Inter), `--font-mono` (system mono, for ids/step numbers/scope names) | Loaded via Google Fonts `<link>` in `index.html` with system fallbacks — degrades fine offline. |
| Type scale | `--text-xs` … `--text-3xl` | Use the scale; don't write a one-off `font-size`. |
| Spacing | `--space-1` (4px) … `--space-8` (72px) | 4px base scale. |
| Shape | `--radius-sm/md/lg/full` | `sm` for pills/inputs-ish elements, `md` for buttons/small cards, `lg` for page-level cards, `full` for pills/avatars/the theme switch. |
| Motion | `--duration-fast/standard/slow`, `--ease-standard` | All zeroed under `prefers-reduced-motion: reduce` automatically — don't hardcode a duration outside these. |
| Accent | `--accent`, `--accent-2`, `--accent-gradient`, `--accent-gradient-soft` | The brand gradient (violet → cyan). `-soft` is the gradient at low opacity for subtle fills (e.g. the invite notice on Login). |
| Semantic | `--success`/`--warning`/`--danger` + matching `-bg` tints | Pair a color with its `-bg` for pills/notices — never pair a semantic color with an unrelated background. |
| Surfaces | `--bg`, `--bg-elevated`, `--surface`, `--surface-solid`, `--surface-border`, `--surface-hover`, `--overlay-blur` | `--surface` is translucent (used with `backdrop-filter: blur(var(--overlay-blur))` — that pairing is `.glass-card`, see below). `--surface-solid` is for things that must not show blur-through (e.g. the Google button). |
| Text | `--text-primary/secondary/muted`, `--text-on-accent` | `-on-accent` is for text sitting directly on `--accent-gradient` (buttons) — it flips automatically per theme for contrast. |
| Role badges | `--role-recruiter`, `--role-hiring_manager`, `--role-interviewer`, `--role-candidate` (+ `-bg` each) | One hue per `User.role` value, used by `.role-<role>` pill classes in `global.css`. Keep any future per-role UI (e.g. a role filter chip) on these same tokens rather than inventing new colors. |

## Utility classes — `src/styles/global.css`

Shared, reused-verbatim classes. Reach for these before writing new CSS:

- **Buttons**: `.btn` + one of `.btn-primary` (gradient, the one primary action per screen), `.btn-outline`, `.btn-ghost`, `.btn-danger`. Add `.btn-sm` for compact contexts (cards, inline actions). Works on both `<button>` and `<a>`.
- **Surfaces**: `.glass-card` — the translucent-blur bordered panel used for every card/modal-like block (Login card, dashboard cards, notice cards). Don't build a second "card" pattern.
- **Pills**: `.pill` + `.pill-success/warning/danger/neutral`, or `.role-<role>` for a user's role. Used for status (Google connected/not, roadmap "Live"/"Coming soon") and role labels.
- **Text**: `.heading-display` (display font + weight, use on every `<h1>`/`<h2>`), `.text-gradient` (accent gradient text, sparingly — brand name and maybe one hero word, not whole paragraphs), `.text-muted`/`.text-secondary`, `.font-mono`.
- **Motion**: `.animate-in` — the standard fade-up-in entrance, applied to a page's top-level content wrapper (see every page in `src/pages/`). Use it for a page's initial mount, not for every child element.
- **Accessibility**: `.sr-only` for screen-reader-only text.

Page- or component-specific layout (grids, one-off spacing, card headers)
belongs in that file's own `*.module.css`, imported as `styles` and applied
with `className={styles.foo}` — never inline `style={{...}}` for anything
reused more than once, and never a bare hex/px value even inline (reference
a token via `var(--...)` if you must use `style`).

## Layout: `AppShell`

Every authenticated page renders inside `AppShell`
(`src/components/AppShell.jsx`) — sticky nav (logo, primary nav links, theme
toggle, user chip with avatar-initials + role, logout) plus a centered
`max-width: 1080px` content column. **Don't rebuild a header/nav on a new
page** — nest its route under the existing `AppShell` layout route in
`App.jsx` (see below) and it inherits the shell automatically.

Full-bleed, unauthenticated pages (`Login`, `NotFound`) don't use `AppShell`
— they mount `BackgroundFX` directly and center a single `.glass-card`.
That's the other layout pattern in the system; a new public-facing page
(e.g. a candidate-facing invite/slot-picker screen reached without being
"in the app") should follow this pattern, not `AppShell`.

`BackgroundFX` (grid + two floating gradient blobs, `aria-hidden`) is the
decorative backdrop for both layouts — mount it once per page, never
stacked.

## Component inventory

| Component | Purpose |
|---|---|
| `Logo` | Brand mark + wordmark, `size="sm"\|"md"\|"lg"`. |
| `ThemeToggle` | The light/dark switch described above. |
| `BackgroundFX` | Decorative grid + blobs backdrop. |
| `Spinner` | Inline loading indicator with optional label; used full-page (centered) for auth checks and inline for in-progress actions. |
| `ScopeBadge` | One Google scope's granted/missing pill (`label`, `granted`). |
| `GoogleConnectionCard` | The Google connection status + connect/reconnect/disconnect card. `variant="summary"` (dashboard, read-only) or `variant="full"` (`/settings/google`, with actions) — **reuse this component for any future "you need to connect/reauthorize Google" prompt** (e.g. Module 4/6/7 hitting `google_not_connected`/`reauth_required`) rather than writing a new one; deep-link to `/settings/google` for the full experience. |
| `AppShell` | Authenticated layout (nav + content column). Exports `ROLE_LABELS` and `initials()` helpers — reuse them for any other place a user's role/initials need to render. |
| `ProtectedRoute` | Route guard: loading → spinner, error → retry card, unauthenticated → redirect to `/login`, authenticated → renders nested route. |
| `icons.jsx` | The whole icon set as small named exports (`IconSun`, `IconGoogle`, `IconCalendar`, …). Add new icons here, not as one-off inline SVGs in a page. |

## Routing & auth pattern

`App.jsx` is the full route map:

```jsx
<Route path="/login" element={<Login />} />
<Route path="/auth/complete" element={<AuthComplete />} />

<Route element={<ProtectedRoute />}>
  <Route element={<AppShell />}>
    <Route path="/dashboard" element={<Dashboard />} />
    <Route path="/settings/google" element={<GoogleConnection />} />
    {/* add new authenticated pages here */}
  </Route>
</Route>
```

**Adding a new authenticated page** (the common case for every future
module):
1. Create `src/pages/YourPage.jsx` + `src/pages/YourPage.module.css`.
2. Wrap its top-level content in `<div className="animate-in">`.
3. Pull data via `useAuth()` (current user) and functions you add to
   `src/lib/api.js` — never `fetch()` inline in the component.
4. Add `<Route path="/your-path" element={<YourPage />} />` **inside** the
   existing `AppShell` layout route in `App.jsx`.
5. If it should appear in primary nav, add a `NavLink` in
   `AppShell.jsx`'s `styles.navLinks` block (there's already a disabled
   "Interviews" placeholder there to replace once Module 2 ships).
6. Role-gate inside the page itself, mirroring the backend's RBAC pattern
   (`CONVENTIONS.md`): check `user.role` from `useAuth()` and render a
   "not available for your role" state rather than hiding the route
   entirely (the backend is the real enforcement; the frontend check is UX).
7. Google-scope-gate the same way: if the page needs Calendar/Gmail and
   `user.google_connected` is false or the relevant scope is missing, show a
   prompt using `GoogleConnectionCard` / a link to `/settings/google` instead
   of letting the action fail server-side first.

A new **unauthenticated/public** page (candidate slot-picking from an email
link, an offer accept/decline landing page, etc.) follows `Login.jsx`'s
pattern instead: no `AppShell`, mount `BackgroundFX` + a single centered
`.glass-card`, and if it doesn't require a WorkHire login, don't route it
through `ProtectedRoute`.

## API client convention — `src/lib/api.js`

The **only** file allowed to call the backend. Add a function per endpoint
here (`api.someAction = (...) => request(...)`), never call `fetch()` from a
component — this is the same rule as the backend's "all config through
`config.py`", applied to the frontend's one external dependency.

- Every request sends `credentials: "include"` (the session lives in an
  httpOnly cookie — see AUTH_MODULE.md).
- Non-2xx responses throw an `ApiError` with `.status`, `.detail`, `.reason`
  populated from the backend's `{ detail, reason? }` JSON shape. Branch on
  `.detail` for the known values the backend defines:
  `google_not_connected`, `google_scope_missing:<scope>`, `reauth_required`,
  `not_authenticated` / `invalid_session` (treat both as logged-out).
- A real OAuth redirect (`GET /auth/google/login`) is **not** a `fetch()`
  target — `api.googleLoginUrl(inviteToken)` returns a URL for
  `window.location.href` or an `<a href>`, since it's a full browser
  navigation into Google's consent screen.

## Accessibility baseline

- Every interactive icon-only control needs an `aria-label` (see
  `ThemeToggle`, the logout button in `AppShell`).
- Focus is always visible — the global `:focus-visible` ring in
  `global.css` — never add `outline: none` without replacing it.
- Color pairs (text/background, pill text/pill background) are chosen for
  AA contrast in both themes; if you introduce a new color pair, check both
  themes, not just the one you're looking at while building.
- Respect `prefers-reduced-motion` — it's handled globally for the duration
  tokens and blob animation; don't add a new animation that ignores it.

## Known gaps / follow-ups for other modules

- **Backend doesn't redirect OAuth errors to the frontend.** If
  `resolve_role_on_first_login` rejects a login, `/auth/google/callback`
  raises an `HTTPException` directly instead of redirecting to
  `FRONTEND_URL/login?error=...` — the user sees a raw backend JSON error
  instead of `AuthComplete`'s friendly message. Fixing it is a small change
  to `backend/app/auth/router.py`'s `callback()`, but it's an auth-module
  change, so it's flagged here rather than made silently.
- **No "intended destination" preservation** on the login redirect — after
  signing in you always land on `/dashboard`, not wherever you were trying
  to go before being bounced to `/login`. Not worth the complexity yet with
  only one authenticated destination; revisit once there are enough pages
  that this matters.
- Role-specific dashboards don't exist yet — `Dashboard.jsx` is the same for
  every role today, just with a different role pill and Google status.
  Module 2's recruiter view, Module 2B's interviewer profile form, etc.
  should each get their own route per "Adding a new authenticated page"
  above rather than being crammed into `Dashboard.jsx` with role branches.
