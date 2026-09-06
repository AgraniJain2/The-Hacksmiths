"""Smart Interview Scheduler - core scheduling engine.

Public surface (import from here):

* Data contract - ``models``
* Config - ``SchedulingConfig``, ``PoolPolicy``, ``AssignmentConfig``,
  ``SkillMatchMode``, ``SeniorityMode``, ``SENIORITY_ORDER``
* Pool resolution (step 4a) - ``resolve_interviewer_pool`` / ``PoolResolutionResult``
* Feasibility (step 4b) - ``run_feasibility`` / ``compute_feasible_slots`` /
  ``feasible_interviewers_at`` / ``feasible_interviewers_at_fixed_time``
* Escalation - ``escalate_to_manual_scheduling`` / ``escalate_if_no_feasible_slot``
* N-seat assignment (step 6) - ``PanelAssignmentAgent`` (deterministic, no LLM),
  ``rank_interviewers``, ``AssignmentOutcome``, ``SeatError``
* Reservation ledger - ``ReservationLedger``
* State machine (steps 6 & 8) - ``InterviewStateMachine``,
  ``InvalidTransitionError``, ``BookingConflictError``
* Orchestration - ``find_feasible_slots`` / ``assign_panel`` / ``run_happy_path``
* Providers - ``scheduler.providers`` (interfaces + in-memory mocks)

See ``Documentation/WORKFLOW.md`` for the workflow and ``SCHEDULER.md`` for the
design rationale (feasibility vs. ranking split, seniority rule, working-hours
precedence, reservation-at-offer locking, per-seat cascade).
"""

from . import models
from .assignment import (
    AssignmentOutcome,
    PanelAssignmentAgent,
    SeatError,
    rank_interviewers,
)
from .config import (
    SENIORITY_ORDER,
    AssignmentConfig,
    PoolPolicy,
    SchedulingConfig,
    SeniorityMode,
    SkillMatchMode,
)
from .escalation import escalate_if_no_feasible_slot, escalate_to_manual_scheduling
from .feasibility import (
    compute_feasible_slots,
    feasible_interviewers_at,
    feasible_interviewers_at_fixed_time,
    run_feasibility,
)
from .pipeline import (
    FeasibilityOutcome,
    PanelOutcome,
    assign_panel,
    find_feasible_slots,
    run_happy_path,
)
from .pool import PoolResolutionResult, resolve_interviewer_pool
from .reservations import Reservation, ReservationLedger
from .state_machine import (
    BookingConflictError,
    InterviewStateMachine,
    InvalidTransitionError,
)
from .tokens import generate_confirmation_token, generate_link_token

__all__ = [
    "models",
    "SchedulingConfig",
    "PoolPolicy",
    "AssignmentConfig",
    "SkillMatchMode",
    "SeniorityMode",
    "SENIORITY_ORDER",
    "resolve_interviewer_pool",
    "PoolResolutionResult",
    "run_feasibility",
    "compute_feasible_slots",
    "feasible_interviewers_at",
    "feasible_interviewers_at_fixed_time",
    "escalate_to_manual_scheduling",
    "escalate_if_no_feasible_slot",
    "PanelAssignmentAgent",
    "rank_interviewers",
    "AssignmentOutcome",
    "SeatError",
    "ReservationLedger",
    "Reservation",
    "InterviewStateMachine",
    "InvalidTransitionError",
    "BookingConflictError",
    "find_feasible_slots",
    "assign_panel",
    "run_happy_path",
    "FeasibilityOutcome",
    "PanelOutcome",
    "generate_link_token",
    "generate_confirmation_token",
]
