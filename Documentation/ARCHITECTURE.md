# Architecture

## Stack

| Layer | Choice | Why |
|---|---|---|
| Backend | Python + FastAPI | Async-native, typed request/response models via Pydantic, mature Google API client libraries (`google-auth`, `google-api-python-client`) that we depend on heavily. |
| ORM / migrations | SQLAlchemy + Alembic | Explicit schema, reviewable migrations — important with several people extending the same tables (`Interview` especially). |
| Database (dev) | SQLite (`backend/dev.db`) | Zero setup — anyone can clone and run without installing a DB server. |
| Database (prod / scale demo) | PostgreSQL | Needed the moment any feature relies on row-level locking (`SELECT ... FOR UPDATE` when creating an interviewer offer — see [WORKFLOW.md](WORKFLOW.md#6-interviewer-assignment--cascade)) or handles concurrent writers. SQLite's locking is coarser (whole-file), which is fine for a single-dev happy-path demo but not for proving the race-condition guard actually works. |
| Auth | Google OAuth 2.0 (Authorization Code + offline access) | We need standing access to Calendar/Gmail on the user's behalf *after* they've left the browser (background scheduling, reminders) — that requires a refresh token, which only the offline-access OAuth flow provides. See [AUTH_MODULE.md](AUTH_MODULE.md). |
| External APIs | Google Calendar API, Gmail API | Free/busy checks, event creation with Meet conferencing, and sending notifications, all through the same Google identity a user already has. |
| Frontend | Not yet decided/built | — |

## System diagram

```mermaid
flowchart LR
    subgraph Client
        FE["Frontend (TBD)"]
    end

    subgraph Backend["FastAPI backend (backend/app)"]
        AUTH["auth module\n(login/callback/session)"]
        API["Feature APIs\n(interviews, slots, bookings)"]
        SCHED["Scheduling logic\n(availability + slot ranking)"]
    end

    DB[("Postgres / SQLite\nUsers, OAuthTokens,\nInterviews, Bookings")]

    subgraph Google["Google APIs"]
        GOAUTH["OAuth 2.0"]
        GCAL["Calendar API\n(freebusy, events)"]
        GMAIL["Gmail API\n(send)"]
    end

    FE -- session cookie --> API
    FE -- redirect --> AUTH
    AUTH -- code exchange --> GOAUTH
    AUTH --> DB
    API --> SCHED
    SCHED -- "get_valid_access_token()" --> AUTH
    SCHED --> GCAL
    API --> GMAIL
    API --> DB
```

The key architectural rule: **feature modules never talk to Google or hold
tokens directly.** Every Calendar/Gmail call goes through
`google_oauth.get_valid_access_token(db, user_id)` in the auth module, which
handles refreshing an expiring token and raises a typed `ReauthRequired`
exception if the connection is dead. This keeps token lifecycle logic in one
auditable place instead of scattered across every module that needs Google
access — see [AUTH_MODULE.md](AUTH_MODULE.md#using-auth-from-your-module).

## Trade-offs (be ready to explain these in your module's walkthrough)

**Why FastAPI over Node/Express?**
Team familiarity with Python, and the Google API Python client libraries are
more mature/better documented than their Node equivalents for the specific
combination we need (OAuth + Calendar + Gmail together). Node would've been an
equally reasonable choice — this wasn't a technical necessity, it was a team
call made early and everything is now built on it.

**Why SQL (Postgres) over NoSQL?**
The core data is inherently relational — interviews have participants, which
have availability windows, which produce offers, which reference calendar
events. Modeling that in a document store means duplicating relationships or
doing joins in application code. We also need transactional guarantees (the
interviewer-assignment lock, see below) that SQL gives natively.

**Why sequential assignment instead of broadcasting to the whole interviewer
pool at once?**
An earlier version of this design had the system notify every eligible pool
member simultaneously and let whoever accepted first claim the seat — that
needs an N-way race guard (multiple simultaneous acceptances competing for a
limited number of seats). We moved to deterministic, load-balanced ranking
instead: compute who's eligible and free, pick the one with the lowest
recent interview count, and only ask the *next*-ranked person if the current
one declines or times out. This is simpler to reason about and implement
correctly (only one offer is ever outstanding per interview, so there's no
multi-way race), and it directly produces fair load distribution as a side
effect rather than needing a separate fairness pass. The trade-off: a
cascade through several declines is slower to land a booking than a
broadcast would be — acceptable for interview scheduling, where minutes of
extra latency don't matter, but would be the wrong call for something
latency-sensitive.

**Why REST over GraphQL?**
Small, fixed set of resources (interviews, slots, bookings) with no deep
nested-query needs from the frontend — GraphQL's flexibility would be paying
for a problem we don't have, at the cost of more setup time we don't have
either.

**Monolith vs. microservices?**
Single FastAPI app with clearly separated modules (`auth/`, and one folder per
feature module going forward), not a monolith-as-one-file and not
microservices. Guideline #2 asks for "clear separation of concerns," not
network-separated services — splitting into real microservices during a
hackathon would spend the clock on deployment/ops instead of the actual
scheduling logic that's being evaluated.

**What breaks first at 100,000 active users?**
In order: (1) SQLite — falls over almost immediately under concurrent writes,
must be Postgres; (2) the naive Free/Busy-per-request pattern — hitting
Google's Calendar API synchronously on every availability check will hit rate
limits fast, needs caching/batching; (3) a single-instance FastAPI process —
needs horizontal scaling behind a load balancer, with sessions validated via
JWT (already stateless — no server-side session store to bottleneck) so this
part actually scales cleanly already.
