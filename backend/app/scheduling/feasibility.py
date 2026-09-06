"""Feasibility engine - workflow step 4 (replaces the old scored matching engine).

Binary, not ranked: for each start time inside the candidate's submitted
availability windows, count the eligible interviewers who are *individually*

  (a) free on their calendar,
  (b) inside THEIR own working hours (their timezone), and
  (c) buffer-respecting around adjacent events,

and keep the slot if at least ``panelists_required`` pass all three. Which N
people actually get the seats is decided later, deterministically, once the
candidate fixes a time (``assignment.py``).

Two layers, same as before:

* pure cores - :func:`feasible_interviewers_at`, :func:`compute_feasible_slots` -
  no I/O, no LLM;
* thin orchestrators - :func:`run_feasibility`,
  :func:`feasible_interviewers_at_fixed_time` - which fetch free/busy through the
  injected :class:`CalendarProvider`.

Why no combinations solver: the eligible pool is already skill/seniority filtered
(typically 2-8 people) and feasibility only needs a *per-interviewer* yes/no plus
a count. There is nothing to optimise here - the ranking that picks the panel is a
separate, deterministic step.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Sequence, Set, Tuple

from .config import SchedulingConfig
from .models import (
    CandidateAvailability,
    FeasibilityResult,
    FeasibleSlot,
    FreeBusyBlock,
    Interviewer,
    InterviewRequest,
    Round,
    TimeRange,
)
from .pool import PoolResolutionResult
from .providers.interfaces import CalendarProvider
from .timeutils import (
    buffered_interval,
    ensure_utc,
    has_busy_conflict,
    is_within_working_hours,
    iter_slot_starts,
)

# Shown directly to the candidate whenever no slot clears the bar. Deliberately
# generic - unlike `no_match_reason` (recruiter-facing, names the specific
# blocker: pool size, skills, working hours, etc.), the candidate gets no
# internal scheduling detail, just what happens next. See
# Documentation/IMPLEMENTATION_PLAN.md Phase 0.6.
CANDIDATE_NO_MATCH_MESSAGE = (
    "We couldn't find a time that works for everyone yet. A recruiter has "
    "been notified and will follow up with you directly."
)


def _slot_id(start: datetime, end: datetime) -> str:
    return f"{int(ensure_utc(start).timestamp())}-{int(ensure_utc(end).timestamp())}"


def feasible_interviewers_at(
    *,
    slot_start: datetime,
    slot_end: datetime,
    eligible_pool: Sequence[Interviewer],
    interviewer_busy: Dict[str, Sequence[FreeBusyBlock]],
    round_: Round,
    reservations=None,
) -> List[str]:
    """Pure: the ids in ``eligible_pool`` that pass all three checks for this slot.

    If ``reservations`` (a ``ReservationLedger``) is given, an interviewer already
    holding an overlapping reservation from another interview/seat is also excluded
    - this is the double-booking guard used on the live recompute at assignment
    time.
    """

    ids: List[str] = []
    if reservations is not None:
        res_start, res_end = buffered_interval(slot_start, slot_end, round_)
    for interviewer in eligible_pool:
        if not is_within_working_hours(
            slot_start, slot_end, interviewer.working_hours, interviewer.timezone
        ):
            continue
        if has_busy_conflict(
            interviewer_busy.get(interviewer.interviewer_id, []), slot_start, slot_end, round_
        ):
            continue
        if reservations is not None and not reservations.is_free(
            interviewer.interviewer_id, res_start, res_end
        ):
            continue
        ids.append(interviewer.interviewer_id)
    return ids


def compute_feasible_slots(
    *,
    request: InterviewRequest,
    round_: Round,
    candidate_availability: CandidateAvailability,
    eligible_pool: Sequence[Interviewer],
    interviewer_busy: Dict[str, Sequence[FreeBusyBlock]],
    config: SchedulingConfig,
    now: Optional[datetime] = None,
) -> List[FeasibleSlot]:
    """Pure: slice every candidate window into slots, keep those with >= N feasible."""

    n = request.panelists_required
    now = ensure_utc(now or datetime.now(timezone.utc))
    duration = timedelta(minutes=round_.duration_minutes)
    granularity = timedelta(minutes=config.assignment.slot_granularity_minutes)

    by_id: Dict[str, FeasibleSlot] = {}
    for window in candidate_availability.windows:
        window_start = max(ensure_utc(window.start), now)  # never propose a past slot
        window_end = ensure_utc(window.end)
        for start in iter_slot_starts(window_start, window_end, duration, granularity):
            end = start + duration
            feasible_ids = feasible_interviewers_at(
                slot_start=start,
                slot_end=end,
                eligible_pool=eligible_pool,
                interviewer_busy=interviewer_busy,
                round_=round_,
            )
            if len(feasible_ids) >= n:
                sid = _slot_id(start, end)
                by_id[sid] = FeasibleSlot(
                    slot_id=sid,
                    start=start,
                    end=end,
                    feasible_interviewer_ids=feasible_ids,
                    feasible_count=len(feasible_ids),
                )

    return sorted(by_id.values(), key=lambda s: ensure_utc(s.start))


def _busy_for_pool(
    pool: Sequence[Interviewer], calendar: CalendarProvider, time_range: TimeRange
) -> Tuple[Dict[str, Sequence[FreeBusyBlock]], Set[str]]:
    """Returns (busy-by-interviewer, ids whose calendar couldn't actually be
    checked - a dead Google connection, not a real "confirmed free" result).
    Callers must exclude the latter from the eligible pool before computing
    feasibility - an empty busy list for them means "never queried," not
    "verified free" (Phase 3's ReauthRequired handling, see models.py's
    FreeBusyResponse.reauth_required)."""
    busy: Dict[str, Sequence[FreeBusyBlock]] = {}
    reauth_required: Set[str] = set()
    for interviewer in pool:
        fb = calendar.get_free_busy(interviewer.interviewer_id, "interviewer", time_range)
        busy[interviewer.interviewer_id] = fb.busy
        if fb.reauth_required:
            reauth_required.add(interviewer.interviewer_id)
    return busy, reauth_required


def run_feasibility(
    request: InterviewRequest,
    round_: Round,
    pool_result: PoolResolutionResult,
    candidate_availability: CandidateAvailability,
    calendar: CalendarProvider,
    config: SchedulingConfig | None = None,
    now: Optional[datetime] = None,
) -> FeasibilityResult:
    """Fetch interviewer free/busy and run the pure core. Empty result carries a reason."""

    config = config or SchedulingConfig()
    generated_at = ensure_utc(now or datetime.now(timezone.utc))

    def _empty(reason: str, reauth_ids: Sequence[str] = ()) -> FeasibilityResult:
        return FeasibilityResult(
            request_id=request.request_id,
            candidate_id=request.candidate_id,
            panelists_required=request.panelists_required,
            feasible_slots=[],
            no_match_reason=reason,
            candidate_message=CANDIDATE_NO_MATCH_MESSAGE,
            reauth_required_interviewer_ids=sorted(reauth_ids),
            generated_at=generated_at,
        )

    if not pool_result.sufficient:
        return _empty(pool_result.reason or "insufficient interviewer pool")
    if not candidate_availability.windows:
        return _empty("candidate has not submitted any availability windows")

    window_start = min(ensure_utc(w.start) for w in candidate_availability.windows)
    window_end = max(ensure_utc(w.end) for w in candidate_availability.windows)
    time_range = TimeRange(start=window_start, end=window_end)
    interviewer_busy, reauth_ids = _busy_for_pool(pool_result.pool, calendar, time_range)
    # Never trust an unchecked calendar as "confirmed free" - see _busy_for_pool.
    verified_pool = [iv for iv in pool_result.pool if iv.interviewer_id not in reauth_ids]

    slots = compute_feasible_slots(
        request=request,
        round_=round_,
        candidate_availability=candidate_availability,
        eligible_pool=verified_pool,
        interviewer_busy=interviewer_busy,
        config=config,
        now=generated_at,
    )
    if not slots:
        reason = (
            f"no time in the candidate's submitted availability has >= "
            f"{request.panelists_required} qualified interviewer(s) free "
            f"(eligible pool of {pool_result.matched}, duration {round_.duration_minutes}m "
            f"+ buffers {round_.buffer_minutes_before}/{round_.buffer_minutes_after}m)"
            + (f" - {len(reauth_ids)} of them couldn't be checked (dead Google connection)" if reauth_ids else "")
        )
        return _empty(reason, reauth_ids)

    return FeasibilityResult(
        request_id=request.request_id,
        candidate_id=request.candidate_id,
        panelists_required=request.panelists_required,
        feasible_slots=slots,
        no_match_reason=None,
        reauth_required_interviewer_ids=sorted(reauth_ids),
        generated_at=generated_at,
    )


def feasible_interviewers_at_fixed_time(
    request: InterviewRequest,
    round_: Round,
    pool_result: PoolResolutionResult,
    slot_start: datetime,
    slot_end: datetime,
    calendar: CalendarProvider,
    reservations=None,
    now: Optional[datetime] = None,  # noqa: ARG001 - kept for signature symmetry
) -> List[str]:
    """Live recompute (workflow step 6): who is *still* feasible at the fixed time.

    Re-fetches free/busy for a narrow range around the chosen slot and also honours
    the reservation ledger, so calendars/reservations that changed since the
    candidate selected are reflected.
    """

    if not pool_result.sufficient:
        return []
    time_range = TimeRange(
        start=ensure_utc(slot_start) - timedelta(hours=1),
        end=ensure_utc(slot_end) + timedelta(hours=1),
    )
    interviewer_busy, reauth_ids = _busy_for_pool(pool_result.pool, calendar, time_range)
    # Same safe-exclusion as run_feasibility (see _busy_for_pool) - this
    # function's plain List[str] return has no room to also surface *why*
    # someone's missing, so that's only ever shown via FeasibilityResult
    # (Module 4's display); this live re-check (Module 6) just has to not
    # wrongly treat a dead connection as "confirmed free."
    verified_pool = [iv for iv in pool_result.pool if iv.interviewer_id not in reauth_ids]
    return feasible_interviewers_at(
        slot_start=slot_start,
        slot_end=slot_end,
        eligible_pool=verified_pool,
        interviewer_busy=interviewer_busy,
        round_=round_,
        reservations=reservations,
    )
