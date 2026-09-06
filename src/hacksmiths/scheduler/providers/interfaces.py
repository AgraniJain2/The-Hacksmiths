"""Provider interfaces (ports) for every external dependency of the scheduler core.

The engine depends only on these ABCs and on the data-contract models - never on a
URL or an HTTP client. Swapping the in-memory mocks for real HTTP-backed
implementations later is: write one subclass per ABC and change the single wiring
point (a FastAPI ``Depends()`` factory).

Out of scope for the scheduling core (teammate-owned, not represented here):
Google OAuth / RBAC, Gmail send, Calendar ``events.insert`` + Meet link, ``.ics``
generation, the signed-link UX for candidate availability & slot selection, and
the reminder cron job.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Literal, Optional

from ..models import (
    Candidate,
    CandidateAvailability,
    FreeBusyResponse,
    Interview,
    Interviewer,
    InterviewerLoadSnapshot,
    InterviewRequest,
    InterviewSeat,
    TimeRange,
)

SeatNotification = Literal["seat_offered", "seat_accepted", "seat_released"]


class CalendarProvider(ABC):
    """Free/busy lookup for an interviewer over a time range.

    (Candidates submit availability windows directly and have no calendar here.)
    """

    @abstractmethod
    def get_free_busy(
        self,
        owner_id: str,
        owner_type: Literal["candidate", "interviewer"],
        time_range: TimeRange,
    ) -> FreeBusyResponse:
        # TODO: replace with real API call once available (Google Calendar
        # freeBusy.query / MS Graph getSchedule via the backend service).
        raise NotImplementedError


class CandidateRepository(ABC):
    @abstractmethod
    def get_candidate(self, candidate_id: str) -> Candidate:
        # TODO: replace with real API call once available.
        raise NotImplementedError


class InterviewerRepository(ABC):
    @abstractmethod
    def get_interviewer(self, interviewer_id: str) -> Interviewer:
        # TODO: replace with real API call once available.
        raise NotImplementedError

    @abstractmethod
    def list_interviewers(self, active_only: bool = False) -> List[Interviewer]:
        """The interviewer directory. Pool resolution filters this down further."""
        # TODO: replace with real API call once available (paginated list / search).
        raise NotImplementedError


class AvailabilityRepository(ABC):
    """Stores the candidate's submitted availability windows (workflow step 3)."""

    @abstractmethod
    def get_availability(self, request_id: str) -> CandidateAvailability:
        # TODO: replace with real API call once available.
        raise NotImplementedError

    @abstractmethod
    def save_availability(self, availability: CandidateAvailability) -> None:
        # TODO: replace with real API call once available.
        raise NotImplementedError


class InterviewerLoadProvider(ABC):
    """Rolling load stats for ranking interviewers when filling seats (step 6)."""

    @abstractmethod
    def get_load_snapshot(
        self, interviewer_id: str, as_of: "object"
    ) -> InterviewerLoadSnapshot:
        # `as_of` is a datetime; typed loosely to avoid importing datetime here.
        # TODO: replace with real API call once available (count confirmed
        # interviews in the trailing rolling_window_days + last assigned time).
        raise NotImplementedError


class NotificationProvider(ABC):
    """Outbound messaging. Real implementations fan out to email / SMS / chat.

    The core only calls the seat-offer, seat-result, panel-complete,
    interview-cancelled and recruiter-escalation hooks; the final confirmation
    email with the ``.ics`` invite is the teammate-owned dispatch step.
    """

    @abstractmethod
    def send_seat_offer(self, interview: Interview, seat: InterviewSeat) -> None:
        # TODO: replace with real API call once available.
        raise NotImplementedError

    @abstractmethod
    def send_seat_filled(self, interview: Interview, seat: InterviewSeat) -> None:
        # TODO: replace with real API call once available.
        raise NotImplementedError

    @abstractmethod
    def send_seat_released(
        self, interview: Interview, seat: InterviewSeat, reason: str
    ) -> None:
        # TODO: replace with real API call once available.
        raise NotImplementedError

    @abstractmethod
    def send_panel_complete(self, interview: Interview) -> None:
        # TODO: replace with real API call once available.
        raise NotImplementedError

    @abstractmethod
    def send_interview_cancelled(self, interview: Interview, reason: str) -> None:
        # TODO: replace with real API call once available.
        raise NotImplementedError

    @abstractmethod
    def notify_recruiter_manual_scheduling(
        self, request: InterviewRequest, reason: str
    ) -> None:
        """Escalation hook: the automated pipeline gave up, a human takes over."""
        # TODO: replace with real API call once available.
        raise NotImplementedError
