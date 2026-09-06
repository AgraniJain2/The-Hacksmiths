"""Orchestration - composes the scheduling-core steps.

A FastAPI layer would call these with providers resolved via ``Depends()``.
Nothing here reaches for a URL or an HTTP client.

Two entry points mirror the two decision points in the workflow:

* :func:`find_feasible_slots` - workflow step 4. Resolve the pool, load the
  candidate's submitted availability, compute the binary-feasible slots. No slots
  -> escalate. Otherwise the candidate is handed the list to pick from (step 5,
  teammate-owned UI).
* :func:`assign_panel` - workflow step 6. Given the candidate's chosen slot id,
  live-recompute who is still feasible at that fixed time, then run the
  deterministic N-seat assignment (parallel offers + per-seat cascade).

:func:`run_happy_path` is a convenience for demos/tests: find -> auto-pick the
first feasible slot -> assign -> auto-accept every offered seat.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Literal, Optional

from .assignment import PanelAssignmentAgent
from .config import PoolPolicy, SchedulingConfig
from .escalation import escalate_to_manual_scheduling
from .feasibility import feasible_interviewers_at_fixed_time, run_feasibility
from .models import FeasibilityResult, Interview, InterviewRequest, Round
from .pool import PoolResolutionResult, resolve_interviewer_pool
from .providers.interfaces import (
    AvailabilityRepository,
    CalendarProvider,
    InterviewerLoadProvider,
    InterviewerRepository,
    NotificationProvider,
)
from .reservations import ReservationLedger
from .state_machine import InterviewStateMachine


@dataclass
class FeasibilityOutcome:
    status: Literal["awaiting_candidate_selection", "manual_scheduling_required"]
    request: InterviewRequest
    pool_result: PoolResolutionResult
    feasibility: FeasibilityResult
    reason: Optional[str] = None


@dataclass
class PanelOutcome:
    status: Literal["panel_complete", "assigning_panel", "manual_scheduling_required"]
    request: InterviewRequest
    interview: Interview
    reason: Optional[str] = None
    # Interviewers feasible at the fixed chosen time - carry it so a caller can
    # continue the per-seat cascade (record a decline / process a timeout) without
    # recomputing.
    feasible_ids_at_slot: List[str] = field(default_factory=list)


def find_feasible_slots(
    request: InterviewRequest,
    round_: Round,
    *,
    interviewer_repo: InterviewerRepository,
    availability_repo: AvailabilityRepository,
    calendar: CalendarProvider,
    notifier: NotificationProvider,
    config: Optional[SchedulingConfig] = None,
    pool_policy: Optional[PoolPolicy] = None,
    now: Optional[datetime] = None,
) -> FeasibilityOutcome:
    config = config or SchedulingConfig()
    pool_policy = pool_policy or config.pool_policy

    pool_result = resolve_interviewer_pool(
        request, interviewer_repo.list_interviewers(active_only=pool_policy.require_active), pool_policy
    )
    availability = availability_repo.get_availability(request.request_id)
    feasibility = run_feasibility(
        request, round_, pool_result, availability, calendar, config=config, now=now
    )

    if not feasibility.feasible_slots:
        reason = feasibility.no_match_reason or "no feasible slot in the candidate's availability"
        updated = escalate_to_manual_scheduling(request, reason, notifier)
        return FeasibilityOutcome(
            "manual_scheduling_required", updated, pool_result, feasibility, reason
        )

    return FeasibilityOutcome(
        "awaiting_candidate_selection",
        request.model_copy(update={"status": "awaiting_candidate_selection"}),
        pool_result,
        feasibility,
    )


def assign_panel(
    request: InterviewRequest,
    round_: Round,
    feasibility: FeasibilityResult,
    chosen_slot_id: str,
    *,
    interviewer_repo: InterviewerRepository,
    calendar: CalendarProvider,
    load_provider: InterviewerLoadProvider,
    notifier: NotificationProvider,
    reservations: ReservationLedger,
    config: Optional[SchedulingConfig] = None,
    pool_policy: Optional[PoolPolicy] = None,
    now: Optional[datetime] = None,
) -> PanelOutcome:
    config = config or SchedulingConfig()
    pool_policy = pool_policy or config.pool_policy

    chosen = next((s for s in feasibility.feasible_slots if s.slot_id == chosen_slot_id), None)
    if chosen is None:
        raise ValueError(f"chosen_slot_id {chosen_slot_id!r} is not in the feasible set")

    pool_result = resolve_interviewer_pool(
        request, interviewer_repo.list_interviewers(active_only=pool_policy.require_active), pool_policy
    )
    fixed_feasible = feasible_interviewers_at_fixed_time(
        request, round_, pool_result, chosen.start, chosen.end, calendar, reservations, now=now
    )

    agent = PanelAssignmentAgent(
        load_provider=load_provider, reservations=reservations, notifier=notifier, config=config
    )
    sm = InterviewStateMachine(reservations, notifier, agent)
    interview = sm.create_interview(request, chosen, round_, now=now)

    if len(fixed_feasible) < request.panelists_required:
        reason = (
            f"chosen slot {chosen.start.isoformat()} no longer has "
            f"{request.panelists_required} feasible interviewer(s) on live recompute "
            f"(only {len(fixed_feasible)}) - calendars/reservations changed since selection"
        )
        updated_request = escalate_to_manual_scheduling(request, reason, notifier)
        interview = interview.model_copy(update={"status": "manual_scheduling_required"})
        return PanelOutcome(
            "manual_scheduling_required", updated_request, interview, reason, list(fixed_feasible)
        )

    outcome = sm.assign_panel(
        interview=interview,
        request=request,
        round_=round_,
        feasible_ids_at_slot=fixed_feasible,
        now=now,
    )
    return PanelOutcome(
        outcome.status, outcome.request, outcome.interview, outcome.reason, list(fixed_feasible)
    )


def run_happy_path(
    request: InterviewRequest,
    round_: Round,
    *,
    interviewer_repo: InterviewerRepository,
    availability_repo: AvailabilityRepository,
    calendar: CalendarProvider,
    load_provider: InterviewerLoadProvider,
    notifier: NotificationProvider,
    reservations: Optional[ReservationLedger] = None,
    config: Optional[SchedulingConfig] = None,
    pool_policy: Optional[PoolPolicy] = None,
    now: Optional[datetime] = None,
) -> tuple[FeasibilityOutcome, Optional[PanelOutcome]]:
    """Feasibility -> auto-pick slot[0] -> assign -> auto-accept all offered seats."""

    config = config or SchedulingConfig()
    reservations = reservations or ReservationLedger()

    feas = find_feasible_slots(
        request,
        round_,
        interviewer_repo=interviewer_repo,
        availability_repo=availability_repo,
        calendar=calendar,
        notifier=notifier,
        config=config,
        pool_policy=pool_policy,
        now=now,
    )
    if feas.status == "manual_scheduling_required":
        return feas, None

    chosen_id = feas.feasibility.feasible_slots[0].slot_id
    panel = assign_panel(
        feas.request,
        round_,
        feas.feasibility,
        chosen_id,
        interviewer_repo=interviewer_repo,
        calendar=calendar,
        load_provider=load_provider,
        notifier=notifier,
        reservations=reservations,
        config=config,
        pool_policy=pool_policy,
        now=now,
    )
    if panel.status != "assigning_panel":
        return feas, panel

    agent = PanelAssignmentAgent(
        load_provider=load_provider, reservations=reservations, notifier=notifier, config=config
    )
    interview = panel.interview
    request_out = panel.request
    for seat in list(interview.seats):
        if seat.status == "offered":
            out = agent.handle_seat_response(
                interview=interview,
                request=request_out,
                round_=round_,
                seat_index=seat.seat_index,
                accepted=True,
                feasible_ids_at_slot=[],
                now=now,
            )
            interview, request_out = out.interview, out.request
    final = PanelOutcome(
        "panel_complete" if interview.all_seats_accepted else interview.status,
        request_out,
        interview,
        feasible_ids_at_slot=panel.feasible_ids_at_slot,
    )
    return feas, final
