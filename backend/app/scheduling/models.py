"""Data contract for the Smart Interview Scheduler core.

These Pydantic models are the *wire contract*, shared verbatim with the FastAPI
layer. Every provider interface and every pure function in this package takes and
returns only these types (plus primitives).

Workflow alignment (see ``Documentation/WORKFLOW.md``):

* There is no recruiter "scheduling window" any more. The only time bound is the
  candidate's own submitted availability (:class:`CandidateAvailability`).
* Matching is two-phase: :class:`FeasibilityResult` is a *binary* "which start
  times have >= N qualified interviewers free" answer (step 4); choosing *which*
  N people happens later, deterministically, once the candidate fixes a time
  (step 6, ``assignment.py``).
* A booked :class:`Interview` tracks N seats independently
  (:class:`InterviewSeat`), each offered / accepted / re-offered on its own.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel

SeniorityLevel = Literal["JUNIOR", "MID", "SENIOR", "STAFF", "PRINCIPAL"]

RequestStatus = Literal[
    "collecting_availability",      # waiting on the candidate's availability windows (step 3)
    "awaiting_candidate_selection",  # feasible slots computed, candidate must pick one (step 5)
    "assigning_panel",              # candidate picked a time, seats are being filled (step 6)
    "panel_complete",               # all N seats accepted - ready for event creation (step 7)
    "manual_scheduling_required",   # escalated to a human; terminal for the automated pipeline
    "cancelled",
]

SeatStatus = Literal[
    "pending",    # not yet offered to anyone
    "offered",    # offered to interviewer_id, awaiting their response
    "accepted",   # interviewer_id accepted; seat filled
    "exhausted",  # every eligible interviewer has declined / is unavailable / is reserved
]

InterviewStatus = Literal[
    "assigning_panel",
    "panel_complete",
    "manual_scheduling_required",
    "cancelled",
]


class WorkingHours(BaseModel):
    start: str  # "09:00", local to the owner's timezone
    end: str  # "18:00"


class Candidate(BaseModel):
    candidate_id: str
    name: str
    email: str
    timezone: str  # IANA, e.g. "Asia/Kolkata"


class Interviewer(BaseModel):
    interviewer_id: str
    name: str
    email: str
    timezone: str
    skills: List[str]
    seniority: SeniorityLevel
    interview_types: List[str]  # e.g. ["TECHNICAL_ROUND_1", "TECHNICAL_ROUND_2"]
    working_hours: WorkingHours  # this person's own schedule, in their own timezone
    calendar_id: str
    active: bool = True  # interviewer's active/inactive toggle (step 2B)


class InterviewRequest(BaseModel):
    request_id: str
    candidate_id: str
    interview_type: str  # e.g. "TECHNICAL_ROUND_1", "HR_ROUND"
    required_skills: List[str]
    seniority: SeniorityLevel
    panelists_required: int  # N automatically filled seats
    hiring_manager_email: Optional[str] = None  # named explicitly, NOT pooled or availability-checked
    status: RequestStatus
    created_at: datetime


class Round(BaseModel):
    round_id: str
    interview_type: str
    duration_minutes: int
    buffer_minutes_before: int
    buffer_minutes_after: int
    # Only a display/fallback hint now that the candidate submits explicit windows.
    default_working_hours: WorkingHours


class AvailabilityWindow(BaseModel):
    """A free time window the candidate offered. Stored as UTC instants.

    The candidate submits these in their own timezone via the signed link (step 3);
    the link handler converts to UTC before persisting. ``source_timezone`` is kept
    only so the UI can echo the original local times back.
    """

    start: datetime
    end: datetime
    source_timezone: Optional[str] = None


class CandidateAvailability(BaseModel):
    request_id: str
    candidate_id: str
    windows: List[AvailabilityWindow]
    submitted_at: datetime


class FreeBusyBlock(BaseModel):
    start: datetime
    end: datetime


class TimeRange(BaseModel):
    start: datetime
    end: datetime


class FreeBusyResponse(BaseModel):
    owner_id: str
    owner_type: Literal["candidate", "interviewer"]
    timezone: str
    busy: List[FreeBusyBlock]
    queried_range: TimeRange


class FeasibleSlot(BaseModel):
    """A concrete start time (inside a candidate window) with >= N qualified
    interviewers individually free. No ranking - feasibility is binary."""

    slot_id: str
    start: datetime
    end: datetime
    feasible_interviewer_ids: List[str]
    feasible_count: int


class FeasibilityResult(BaseModel):
    """Output of step 4 (replaces the old scored ``MatchingResult``)."""

    request_id: str
    candidate_id: str
    panelists_required: int
    feasible_slots: List[FeasibleSlot]  # empty => nothing feasible
    no_match_reason: Optional[str] = None  # populated when feasible_slots is empty
    generated_at: datetime


class InterviewerLoadSnapshot(BaseModel):
    """Load stats used to rank interviewers for seat offers (step 6)."""

    interviewer_id: str
    rolling_confirmed_count: int  # confirmed interviews in the trailing rolling_window_days
    last_assigned_at: Optional[datetime] = None  # for round-robin tie-breaking


class InterviewSeat(BaseModel):
    seat_index: int
    interviewer_id: Optional[str] = None
    status: SeatStatus = "pending"
    offered_at: Optional[datetime] = None
    offer_expires_at: Optional[datetime] = None
    responded_at: Optional[datetime] = None
    # everyone who has passed on THIS seat (declined or timed out) - excluded from the cascade
    declined_interviewer_ids: List[str] = []


class Interview(BaseModel):
    interview_id: str
    request_id: str
    candidate_id: str
    interview_type: str
    hiring_manager_email: Optional[str] = None
    slot_start: datetime
    slot_end: datetime
    seats: List[InterviewSeat]  # length == panelists_required
    status: InterviewStatus
    created_at: datetime
    updated_at: datetime
    calendar_event_id: Optional[str] = None  # set by the teammate-owned event-creation step
    meet_link: Optional[str] = None

    @property
    def panel(self) -> List[str]:
        """interviewer_ids of the currently accepted seats."""
        return [s.interviewer_id for s in self.seats if s.status == "accepted" and s.interviewer_id]

    @property
    def all_seats_accepted(self) -> bool:
        return bool(self.seats) and all(s.status == "accepted" for s in self.seats)

    @property
    def has_exhausted_seat(self) -> bool:
        return any(s.status == "exhausted" for s in self.seats)
