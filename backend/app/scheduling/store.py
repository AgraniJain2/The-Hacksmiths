"""In-memory scheduling store - the seam between the HTTP layer (router.py)
and the pure scheduling engine (pipeline.py and friends).

**This is not a database.** State lives in one process's memory and is gone
on restart; it isn't safe across multiple worker processes. It exists
because the engine's own design (see providers/interfaces.py) never talks to
a URL or a DB row - every external dependency is a provider ABC, currently
satisfied only by in-memory mocks. Building the real DB tables from
DATA_MODEL.md and a real Google Calendar adapter is the next backend
milestone (see Documentation/SCHEDULER.md's "provider swap path"); this
store is the honest stand-in until then, using the mock providers Agrani
already wrote and tested rather than inventing a second set.

Two custom providers live here instead of in providers/ because they're
specific to *this* demo backend, not general-purpose test doubles:

* :class:`LiveInterviewerLoadProvider` computes rolling load from this
  store's own interview history - the same "never a stored counter, always
  computed live" rule DATA_MODEL.md specifies for the real DB, just against
  an in-memory dict instead of an ``InterviewParticipant`` table.
* :class:`InboxNotificationProvider` records every engine notification as a
  human-readable inbox entry instead of sending real email - there is no
  Notification Service yet (see MODULE_GUIDE.md's shared section).
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from .assignment import AssignmentOutcome
from .config import SchedulingConfig
from .escalation import escalate_to_manual_scheduling
from .feasibility import feasible_interviewers_at_fixed_time, run_feasibility
from .models import (
    Candidate,
    CandidateAvailability,
    FeasibilityResult,
    Interview,
    Interviewer,
    InterviewerLoadSnapshot,
    InterviewRequest,
    InterviewSeat,
    Round,
    WorkingHours,
)
from .pipeline import FeasibilityOutcome, PanelOutcome, assign_panel, find_feasible_slots
from .pool import resolve_interviewer_pool
from .providers.interfaces import InterviewerLoadProvider, NotificationProvider
from .providers.mock_availability_repository import MockAvailabilityRepository
from .providers.mock_calendar_provider import MockCalendarProvider
from .providers.mock_repositories import MockCandidateRepository, MockInterviewerRepository
from .reservations import ReservationLedger
from .state_machine import InterviewStateMachine
from .timeutils import ensure_utc

UTC = timezone.utc


class NotFoundError(KeyError):
    """A request/interview id that doesn't exist in the store."""


class ForbiddenError(Exception):
    """The caller isn't the owner of the resource they're acting on."""


# --------------------------------------------------------------------------- #
# Providers specific to this demo store
# --------------------------------------------------------------------------- #


class LiveInterviewerLoadProvider(InterviewerLoadProvider):
    """Rolling confirmed-count + last-assigned time, computed from the
    store's own ``interviews`` dict instead of a stored counter."""

    def __init__(self, interviews: Dict[str, Interview], window_days: int = 7) -> None:
        self._interviews = interviews
        self._window_days = window_days

    def get_load_snapshot(self, interviewer_id: str, as_of) -> InterviewerLoadSnapshot:
        as_of_dt = ensure_utc(as_of) if as_of is not None else datetime.now(UTC)
        cutoff = as_of_dt - timedelta(days=self._window_days)
        stamps: List[datetime] = []
        for interview in self._interviews.values():
            for seat in interview.seats:
                if (
                    seat.interviewer_id == interviewer_id
                    and seat.status == "accepted"
                    and seat.responded_at
                ):
                    stamps.append(ensure_utc(seat.responded_at))
        in_window = [d for d in stamps if cutoff <= d <= as_of_dt]
        past = [d for d in stamps if d <= as_of_dt]
        return InterviewerLoadSnapshot(
            interviewer_id=interviewer_id,
            rolling_confirmed_count=len(in_window),
            last_assigned_at=max(past) if past else None,
        )


@dataclass
class Notification:
    id: str
    recipient: str  # interviewer_id, candidate email, or the recruiter's user id
    kind: str
    message: str
    interview_id: Optional[str]
    created_at: datetime
    read: bool = False


class InboxNotificationProvider(NotificationProvider):
    def __init__(self, request_owner: Dict[str, str]) -> None:
        self._request_owner = request_owner
        self.inbox: List[Notification] = []

    def _add(self, recipient: str, kind: str, message: str, interview_id: Optional[str]) -> None:
        self.inbox.append(
            Notification(
                id=uuid.uuid4().hex[:12],
                recipient=recipient,
                kind=kind,
                message=message,
                interview_id=interview_id,
                created_at=datetime.now(UTC),
            )
        )

    def for_recipient(self, *identities: str) -> List[Notification]:
        idset = set(identities)
        return sorted(
            (n for n in self.inbox if n.recipient in idset),
            key=lambda n: n.created_at,
            reverse=True,
        )

    def send_seat_offer(self, interview: Interview, seat: InterviewSeat) -> None:
        self._add(
            seat.interviewer_id,
            "seat_offer",
            f"You've been offered a panel seat on a {interview.interview_type} interview "
            f"at {ensure_utc(interview.slot_start).isoformat()}.",
            interview.interview_id,
        )

    def send_seat_filled(self, interview: Interview, seat: InterviewSeat) -> None:
        self._add(
            seat.interviewer_id,
            "seat_filled",
            f"You're confirmed for the {interview.interview_type} interview at "
            f"{ensure_utc(interview.slot_start).isoformat()}.",
            interview.interview_id,
        )

    def send_seat_released(self, interview: Interview, seat: InterviewSeat, reason: str) -> None:
        if seat.interviewer_id:
            self._add(
                seat.interviewer_id,
                "seat_released",
                f"Your seat on the {interview.interview_type} interview was released: {reason}",
                interview.interview_id,
            )

    def send_panel_complete(self, interview: Interview) -> None:
        for seat in interview.seats:
            if seat.interviewer_id:
                self._add(
                    seat.interviewer_id,
                    "panel_complete",
                    f"Panel confirmed for the {interview.interview_type} interview at "
                    f"{ensure_utc(interview.slot_start).isoformat()}.",
                    interview.interview_id,
                )
        self._add(
            interview.candidate_id,
            "panel_complete",
            f"Your interview panel is confirmed for {ensure_utc(interview.slot_start).isoformat()}.",
            interview.interview_id,
        )

    def send_interview_cancelled(self, interview: Interview, reason: str) -> None:
        for seat in interview.seats:
            if seat.interviewer_id:
                self._add(
                    seat.interviewer_id,
                    "interview_cancelled",
                    f"Interview cancelled: {reason}",
                    interview.interview_id,
                )
        self._add(
            interview.candidate_id,
            "interview_cancelled",
            f"Your interview was cancelled: {reason}",
            interview.interview_id,
        )

    def notify_recruiter_manual_scheduling(self, request: InterviewRequest, reason: str) -> None:
        owner = self._request_owner.get(request.request_id, "recruiter")
        self._add(
            owner,
            "escalation",
            f"Interview request {request.request_id} needs manual scheduling: {reason}",
            None,
        )


# --------------------------------------------------------------------------- #
# The store
# --------------------------------------------------------------------------- #


class SchedulingStore:
    def __init__(self) -> None:
        self._lock = threading.RLock()

        self.requests: Dict[str, InterviewRequest] = {}
        self.rounds: Dict[str, Round] = {}
        self.feasibility: Dict[str, FeasibilityResult] = {}
        self.interviews: Dict[str, Interview] = {}
        self.interview_by_request: Dict[str, str] = {}
        self.request_owner: Dict[str, str] = {}  # request_id -> creating user's id

        self.candidate_repo = MockCandidateRepository()
        self.interviewer_repo = MockInterviewerRepository()
        self.availability_repo = MockAvailabilityRepository()
        self.calendar = MockCalendarProvider()
        self.reservations = ReservationLedger()
        self.notifier = InboxNotificationProvider(self.request_owner)
        self.load_provider = LiveInterviewerLoadProvider(self.interviews)
        self.config = SchedulingConfig()

    # -- requests ------------------------------------------------------------

    def create_request(
        self,
        *,
        owner_user_id: str,
        interview_type: str,
        required_skills: List[str],
        seniority: str,
        panelists_required: int,
        duration_minutes: int,
        buffer_minutes_before: int,
        buffer_minutes_after: int,
        hiring_manager_email: Optional[str],
        candidate_name: str,
        candidate_email: str,
        candidate_timezone: str,
    ) -> Tuple[InterviewRequest, Round]:
        with self._lock:
            request_id = f"req-{uuid.uuid4().hex[:10]}"
            now = datetime.now(UTC)

            self.candidate_repo.add(
                Candidate(
                    candidate_id=candidate_email,
                    name=candidate_name,
                    email=candidate_email,
                    timezone=candidate_timezone,
                )
            )
            round_ = Round(
                round_id=f"round-{request_id}",
                interview_type=interview_type,
                duration_minutes=duration_minutes,
                buffer_minutes_before=buffer_minutes_before,
                buffer_minutes_after=buffer_minutes_after,
                default_working_hours=WorkingHours(start="09:00", end="18:00"),
            )
            request = InterviewRequest(
                request_id=request_id,
                candidate_id=candidate_email,
                interview_type=interview_type,
                required_skills=required_skills,
                seniority=seniority,  # type: ignore[arg-type]
                panelists_required=panelists_required,
                hiring_manager_email=hiring_manager_email,
                status="collecting_availability",
                created_at=now,
            )
            self.requests[request_id] = request
            self.rounds[request_id] = round_
            self.request_owner[request_id] = owner_user_id
            return request, round_

    def list_requests(self) -> List[InterviewRequest]:
        return sorted(self.requests.values(), key=lambda r: r.created_at, reverse=True)

    def get_request(self, request_id: str) -> InterviewRequest:
        try:
            return self.requests[request_id]
        except KeyError:
            raise NotFoundError(f"no interview request {request_id!r}") from None

    def get_round(self, request_id: str) -> Round:
        return self.rounds[request_id]

    def find_request_by_candidate_email(self, email: str) -> Optional[InterviewRequest]:
        matches = [r for r in self.requests.values() if r.candidate_id.lower() == email.lower()]
        return max(matches, key=lambda r: r.created_at) if matches else None

    def get_interview_for_request(self, request_id: str) -> Optional[Interview]:
        iid = self.interview_by_request.get(request_id)
        return self.interviews.get(iid) if iid else None

    def get_interview(self, interview_id: str) -> Interview:
        try:
            return self.interviews[interview_id]
        except KeyError:
            raise NotFoundError(f"no interview {interview_id!r}") from None

    def _sync_request_status(self, request: InterviewRequest, interview: Interview) -> InterviewRequest:
        """Once an interview exists, the request's status mirrors it - the
        engine's pipeline only updates Interview.status on its own (see
        assignment.py/state_machine.py); InterviewRequest.status is this
        store's bookkeeping so the recruiter/candidate views stay accurate."""
        if request.status != interview.status and interview.status in (
            "assigning_panel",
            "panel_complete",
            "manual_scheduling_required",
            "cancelled",
        ):
            request = request.model_copy(update={"status": interview.status})
            self.requests[request.request_id] = request
        return request

    # -- availability + feasibility (step 3 -> 4) -----------------------------

    def submit_availability(
        self, request_id: str, windows
    ) -> Tuple[InterviewRequest, FeasibilityOutcome]:
        with self._lock:
            request = self.get_request(request_id)
            round_ = self.get_round(request_id)
            self.availability_repo.save_availability(
                CandidateAvailability(
                    request_id=request_id,
                    candidate_id=request.candidate_id,
                    windows=windows,
                    submitted_at=datetime.now(UTC),
                )
            )
            outcome = find_feasible_slots(
                request,
                round_,
                interviewer_repo=self.interviewer_repo,
                availability_repo=self.availability_repo,
                calendar=self.calendar,
                notifier=self.notifier,
                config=self.config,
            )
            self.requests[request_id] = outcome.request
            self.feasibility[request_id] = outcome.feasibility
            return outcome.request, outcome

    # -- slot selection + panel assignment (step 5 -> 6) ----------------------

    def select_slot(self, request_id: str, slot_id: str) -> Tuple[InterviewRequest, Interview]:
        with self._lock:
            request = self.get_request(request_id)
            round_ = self.get_round(request_id)
            feasibility = self.feasibility.get(request_id)
            if feasibility is None:
                raise ValueError("feasibility has not been computed for this request yet")

            outcome: PanelOutcome = assign_panel(
                request,
                round_,
                feasibility,
                slot_id,
                interviewer_repo=self.interviewer_repo,
                calendar=self.calendar,
                load_provider=self.load_provider,
                notifier=self.notifier,
                reservations=self.reservations,
                config=self.config,
            )
            self.interviews[outcome.interview.interview_id] = outcome.interview
            self.interview_by_request[request_id] = outcome.interview.interview_id
            request = self._sync_request_status(outcome.request, outcome.interview)
            self.requests[request_id] = request
            return request, outcome.interview

    # -- seat responses + interviewer cancel (step 6 continued, step 8) ------

    def respond_to_seat(
        self, interview_id: str, seat_index: int, *, accept: bool, actor_interviewer_id: str
    ) -> Tuple[Interview, InterviewRequest]:
        with self._lock:
            interview = self.get_interview(interview_id)
            request = self.get_request(interview.request_id)
            round_ = self.get_round(interview.request_id)

            if not (0 <= seat_index < len(interview.seats)):
                raise ValueError(f"interview has no seat {seat_index}")
            seat = interview.seats[seat_index]
            if seat.interviewer_id != actor_interviewer_id:
                raise ForbiddenError("this offer wasn't made to you")
            if seat.status != "offered":
                raise ValueError(f"seat {seat_index} is {seat.status!r}, not awaiting a response")

            pool_result = resolve_interviewer_pool(
                request, self.interviewer_repo.list_interviewers(active_only=True), self.config.pool_policy
            )
            feasible_now = feasible_interviewers_at_fixed_time(
                request, round_, pool_result, interview.slot_start, interview.slot_end,
                self.calendar, self.reservations,
            )
            sm = self._state_machine()
            outcome: AssignmentOutcome = sm.respond_to_seat(
                interview=interview,
                request=request,
                round_=round_,
                seat_index=seat_index,
                accepted=accept,
                feasible_ids_at_slot=feasible_now,
            )
            self.interviews[interview_id] = outcome.interview
            request = self._sync_request_status(outcome.request, outcome.interview)
            self.requests[request.request_id] = request
            return outcome.interview, request

    def interviewer_cancel(self, interview_id: str, interviewer_id: str) -> Tuple[Interview, InterviewRequest]:
        with self._lock:
            interview = self.get_interview(interview_id)
            request = self.get_request(interview.request_id)
            round_ = self.get_round(interview.request_id)

            pool_result = resolve_interviewer_pool(
                request, self.interviewer_repo.list_interviewers(active_only=True), self.config.pool_policy
            )
            feasible_now = feasible_interviewers_at_fixed_time(
                request, round_, pool_result, interview.slot_start, interview.slot_end,
                self.calendar, self.reservations,
            )
            sm = self._state_machine()
            outcome: AssignmentOutcome = sm.interviewer_cancel(
                interview=interview,
                request=request,
                round_=round_,
                interviewer_id=interviewer_id,
                feasible_ids_at_slot=feasible_now,
            )
            self.interviews[interview_id] = outcome.interview
            request = self._sync_request_status(outcome.request, outcome.interview)
            self.requests[request.request_id] = request
            return outcome.interview, request

    def candidate_cancel(self, request_id: str, reason: str = "candidate cancelled") -> InterviewRequest:
        with self._lock:
            request = self.get_request(request_id)
            interview = self.get_interview_for_request(request_id)
            if interview is not None and interview.status not in ("cancelled",):
                sm = self._state_machine()
                cancelled = sm.candidate_cancel(interview, reason=reason)
                self.interviews[interview.interview_id] = cancelled
            request = request.model_copy(update={"status": "cancelled"})
            self.requests[request_id] = request
            return request

    def _state_machine(self) -> InterviewStateMachine:
        from .assignment import PanelAssignmentAgent

        agent = PanelAssignmentAgent(
            load_provider=self.load_provider,
            reservations=self.reservations,
            notifier=self.notifier,
            config=self.config,
        )
        return InterviewStateMachine(self.reservations, self.notifier, agent)

    # -- interviewer directory (Module 2B, in-memory) -------------------------

    def upsert_interviewer_profile(
        self,
        *,
        interviewer_id: str,
        name: str,
        email: str,
        skills: List[str],
        seniority: str,
        interview_types: List[str],
        timezone_name: str,
        working_hours_start: str,
        working_hours_end: str,
        active: bool,
    ) -> Interviewer:
        interviewer = Interviewer(
            interviewer_id=interviewer_id,
            name=name,
            email=email,
            timezone=timezone_name,
            skills=skills,
            seniority=seniority,  # type: ignore[arg-type]
            interview_types=interview_types,
            working_hours=WorkingHours(start=working_hours_start, end=working_hours_end),
            calendar_id=f"cal-{interviewer_id}",
            active=active,
        )
        self.interviewer_repo.add(interviewer)
        return interviewer

    def get_interviewer_profile(self, interviewer_id: str) -> Optional[Interviewer]:
        try:
            return self.interviewer_repo.get_interviewer(interviewer_id)
        except KeyError:
            return None

    def list_interviewers(self) -> List[Interviewer]:
        return self.interviewer_repo.list_interviewers()

    def list_offers_for_interviewer(self, interviewer_id: str) -> List[Tuple[Interview, InterviewSeat]]:
        out: List[Tuple[Interview, InterviewSeat]] = []
        for interview in self.interviews.values():
            for seat in interview.seats:
                if seat.interviewer_id == interviewer_id and seat.status in ("offered", "accepted"):
                    out.append((interview, seat))
        out.sort(key=lambda pair: pair[0].slot_start)
        return out


# Process-lifetime singleton - see the module docstring for why this isn't a DB.
_store: Optional[SchedulingStore] = None
_store_lock = threading.Lock()


def get_store() -> SchedulingStore:
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = SchedulingStore()
    return _store
