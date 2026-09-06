# Smart Interview Scheduler — core scheduling engine

Location: `backend/app/scheduling/`. Pure Python + Pydantic, FastAPI-ready
(every model in `scheduling.models` is a `BaseModel`). No module in *this*
package calls a real URL or a DB row — all external dependencies go through
the ABCs in `scheduling.providers.interfaces`. The pure engine itself
(everything in the file list below) is untouched by what's backing those
ABCs.

**Provider wiring status** (Documentation/IMPLEMENTATION_PLAN.md): real,
SQLAlchemy-backed providers (`providers/db_*.py`) and `service.py` (the
`SchedulingService` `router.py` actually calls) replaced the old in-memory
store in Phase 2 — state now survives a restart. `CalendarProvider` is real
Google Calendar as of Phase 3 (`GoogleCalendarProvider` — `freebusy.query`
against each interviewer's own primary calendar; a dead connection reports
`FreeBusyResponse.reauth_required` rather than crashing or lying about
availability, see `feasibility.py`). `mock_*.py` + `fixtures.py` haven't gone
anywhere; they're what this package's own tests (`tests/scheduling/`) are
built on, deliberately independent of whichever real backing exists.

This package implements workflow **steps 4, 6, and the step-8 re-computations**
(see [WORKFLOW.md](WORKFLOW.md)). Auth, the candidate-facing link pages,
Google Calendar/Meet/Gmail, `.ics`, and the reminder job are owned elsewhere.

```
models.py        data contract (candidate availability windows, feasible slots, seats, ...)
config.py        PoolPolicy + AssignmentConfig (no scoring weights — feasibility is binary)
timeutils.py     timezone + working-hours + interval math (+ buffered_interval)
pool.py          resolve_interviewer_pool(...) -> PoolResolutionResult   (step 4a)
feasibility.py   run_feasibility(...) -> FeasibilityResult               (step 4b, pure core + orchestrator)
reservations.py  ReservationLedger — interval-overlap lock, reserved at offer time
assignment.py    PanelAssignmentAgent — deterministic N-seat fill + cascade   (step 6)
escalation.py    escalate_to_manual_scheduling(request, reason, notifier)
state_machine.py InterviewStateMachine — creation, conflict re-check, step-8 exception paths
pipeline.py      find_feasible_slots(...) / assign_panel(...) / run_happy_path(...)
providers/       interfaces.py (ABCs) + mock_*.py (in-memory, tests only) + db_*.py (real, Phase 2) + fixtures.py (6 scenarios)
```

Run the pure-engine tests: `cd backend && pytest tests/scheduling` (57 tests,
~0.1s, no network, no DB — the mocks above). The DB-backed providers and
`service.py` have their own tests in `tests/scheduling_api/` (the HTTP
integration test) and `tests/scheduling_service/` (repository/concurrency
tests) — `cd backend && pytest` runs everything.

---

## 1. Two-phase design: feasibility (binary) then ranking

The old single scored `matching` engine is gone. The workflow splits the decision:

- **Step 4 — feasibility (`feasibility.py`)** answers a *binary* question: which
  start times inside the candidate's submitted windows have **at least N**
  qualified interviewers individually free? No scoring, no ranking, no
  combinations. `FeasibleSlot.feasible_interviewer_ids` just lists who qualifies
  at that time.
- **Step 6 — assignment (`assignment.py`)** happens only after the candidate fixes
  one time. Now — and only now — interviewers are *ranked*, and the top N are
  offered seats.

Why no combinations / solver: the eligible pool is already skill- and
seniority-filtered (typically 2-8 people), and feasibility only needs a
per-interviewer yes/no plus a count. There is nothing to optimise. The panel is
chosen by a transparent lexicographic rank, not a black box.

## 2. Interviewer ranking rule (step 6)

`rank_interviewers` sorts by, in order:

1. **rolling 7-day confirmed interview count, ascending** — burnout prevention /
   load balancing. Window length is `AssignmentConfig.rolling_window_days`.
2. **last-assigned time, ascending** (never-assigned sorts first) — round-robin
   tie-break.
3. interviewer id — stable final tie-break.

Data comes from `InterviewerLoadProvider.get_load_snapshot(id, as_of)`.

## 3. Seniority-matching rule (`config.SeniorityMode`, default `AT_LEAST`)

Seniority is an ordinal ladder (`JUNIOR < MID < SENIOR < STAFF < PRINCIPAL`,
`config.SENIORITY_ORDER`). Default: **interviewer seniority >= requested**. A more
senior person can reliably assess at or below their level, and an exact-band
requirement is the biggest cause of "no interviewer available" in a small org.
`SeniorityMode.EXACT` is available for leveling-calibration rounds.

## 4. Skill-overlap threshold (`config.SkillMatchMode`, default `ALL`)

Default: the interviewer must cover **every** skill in `required_skills` — the
recruiter's list is the minimum competency bar. `ANY` (one overlap, for broad
behavioural rounds) and `RATIO` (`covered/required >= ratio`, for thin pools) are
config switches.

## 5. Active toggle

`resolve_interviewer_pool` drops interviewers with `active == False` when
`PoolPolicy.require_active` is on (the default). Set it False to include everyone.

## 6. Working-hours precedence

- **Each interviewer** is checked against **their own `Interviewer.working_hours`**
  in **their own IANA timezone** (converted to UTC). Someone who works 07:00-15:00
  is never offered a 16:00 slot *even if their calendar is empty* —
  `timeutils.is_within_working_hours`.
- **The candidate** has no working-hours profile and no recruiter window. Their
  bound is the set of `AvailabilityWindow`s they submitted in step 3.
  `Round.default_working_hours` is now only a display/fallback hint.

A slot must fit *entirely* inside the relevant window for that participant's local
day. `Round.buffer_minutes_before/after` additionally pad the free/busy check and
the reservation interval (§8).

Known simplification: `WorkingHours` is time-of-day only, so weekends aren't
excluded — a `timeutils`-only change if wanted.

## 7. No recruiter scheduling window

`InterviewRequest` has **no `scheduling_window`**. The only time bound is the
candidate's submitted availability. If nothing in those windows yields `>= N`
feasible interviewers, that escalates (§9) — the engine never looks past what the
candidate offered.

## 8. Reservation-at-offer locking (`reservations.py`)

`ReservationLedger` is **not** an exact `(id, start)` check. Each reservation is a
**buffered `[start, end)` interval** owned by one `(interview_id, seat_index)`.
`is_free` returns False if any existing reservation for that interviewer overlaps
the queried interval. The lock is taken **when the seat offer is created** (not at
acceptance), so two interviews whose padded times overlap can never both land on
the same person. `InterviewStateMachine.verify_ready_to_finalize` re-checks every
accepted seat's reservation as the hand-off gate to event creation.

## 9. Manual-scheduling escalation — terminal

`escalate_to_manual_scheduling` sets `InterviewRequest.status =
"manual_scheduling_required"` and calls
`NotificationProvider.notify_recruiter_manual_scheduling(request, reason)` with a
specific reason. Triggers:

- `< N` eligible+active interviewers in the directory (pool resolution),
- no candidate window has `>= N` feasible interviewers (feasibility),
- a panel seat's cascade runs out of qualified interviewers (assignment),
- the chosen slot loses feasibility on the live recompute (calendars/reservations
  changed since the candidate picked).

No automatic window expansion or buffer relaxation — a human takes over.

## 10. Per-seat cascade instead of a solver (step 6, `assignment.py`)

`PanelAssignmentAgent` (deterministic — **no LLM anywhere**):

- `fill_pending_seats` — offer each `pending` seat to the next-ranked feasible
  person not already holding/offered a seat here and not already declined for that
  seat; reserve them; notify. Used for the initial parallel offer *and* for
  re-offering one seat.
- `handle_seat_response(accepted)` — accept keeps the reservation and may complete
  the panel; decline releases it, records the decliner on that seat, and cascades
  that seat only.
- `process_timeouts` — expire `offered` seats past `offer_expires_at` and cascade
  them.
- when a seat has no one left → `exhausted` → the whole request escalates.

"Bounded output + fallback" (the original first-prompt requirement, minus the
LLM): the only people it can pick are in the feasible set for the fixed time; its
fallback is the cascade; its terminal fallback is escalation.

## 11. Interview state machine (steps 6 & 8)

`Interview.status`: `assigning_panel → panel_complete | manual_scheduling_required
| cancelled`; `panel_complete → assigning_panel` (an interviewer cancelled, that
seat reopens) `| cancelled`. Seat status: `pending → offered → accepted |
exhausted`.

Step-8 exception paths on `InterviewStateMachine`:

- `candidate_cancel` — release all seats + reservations, notify, terminal
  `cancelled`.
- `candidate_reschedule` — release all, notify held interviewers, reset the
  request to `collecting_availability`; the caller re-collects availability and
  re-runs `find_feasible_slots`.
- `interviewer_cancel(interviewer_id)` — release just that seat, re-cascade it at
  the same fixed time excluding the canceller; others untouched; exhausted →
  escalate.

## 12. Orchestration (`pipeline.py`)

- `find_feasible_slots(request, round_, ...)` → resolve pool, load candidate
  availability, run feasibility. No slots → escalate. Else status
  `awaiting_candidate_selection` + the `FeasibilityResult` for the candidate UI.
- `assign_panel(request, round_, feasibility, chosen_slot_id, ...)` → validate the
  choice, live-recompute feasibility at the fixed time (honouring the reservation
  ledger), create the interview with N seats, run the assignment agent.
- `run_happy_path(...)` → find → auto-pick `feasible_slots[0]` → assign →
  auto-accept every offered seat. Demo/test convenience.

## 13. Provider swap path

Every engine module imports only the ABCs in `providers/interfaces.py` and the
data-contract models — this is what made the Phase 2 swap possible without
touching pool resolution, feasibility, ranking, the assignment agent, or the
state machine at all. Done: `CandidateRepository`, `InterviewerRepository`,
`AvailabilityRepository`, `InterviewerLoadProvider`, `NotificationProvider`
(all real, DB/Resend-backed — `db_*.py` + `app/notifications/`), plus
`ReservationLedger`'s DB-backed replacement (`DbReservationLedger` — not an
ABC itself, see its own docstring for why, but the same swap-at-one-point
principle) and `CalendarProvider` (`GoogleCalendarProvider`, Phase 3 —
Documentation/IMPLEMENTATION_PLAN.md). Every provider ABC now has a real
implementation backing it in the live app.
