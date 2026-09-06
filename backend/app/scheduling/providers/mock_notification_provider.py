"""In-memory :class:`NotificationProvider` that records what it was asked to send.

Tests assert against ``.records`` / ``.manual_escalations`` instead of a mail server.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from ..models import Interview, InterviewRequest, InterviewSeat
from .interfaces import NotificationProvider


@dataclass
class NotificationRecord:
    kind: str  # "seat_offer" | "seat_filled" | "seat_released" | "panel_complete" | "interview_cancelled"
    interview_id: str
    seat_index: Optional[int] = None
    interviewer_id: Optional[str] = None
    reason: Optional[str] = None


@dataclass
class ManualEscalation:
    request_id: str
    reason: str


class MockNotificationProvider(NotificationProvider):
    def __init__(self) -> None:
        self.records: List[NotificationRecord] = []
        self.manual_escalations: List[ManualEscalation] = []

    def _add(self, kind: str, interview: Interview, seat: InterviewSeat | None = None, reason=None):
        self.records.append(
            NotificationRecord(
                kind=kind,
                interview_id=interview.interview_id,
                seat_index=seat.seat_index if seat else None,
                interviewer_id=seat.interviewer_id if seat else None,
                reason=reason,
            )
        )

    def kinds(self) -> List[str]:
        return [r.kind for r in self.records]

    def send_seat_offer(self, interview: Interview, seat: InterviewSeat) -> None:
        self._add("seat_offer", interview, seat)

    def send_seat_filled(self, interview: Interview, seat: InterviewSeat) -> None:
        self._add("seat_filled", interview, seat)

    def send_seat_released(self, interview: Interview, seat: InterviewSeat, reason: str) -> None:
        self._add("seat_released", interview, seat, reason)

    def send_panel_complete(self, interview: Interview) -> None:
        self._add("panel_complete", interview)

    def send_interview_cancelled(self, interview: Interview, reason: str) -> None:
        self._add("interview_cancelled", interview, reason=reason)

    def notify_recruiter_manual_scheduling(self, request: InterviewRequest, reason: str) -> None:
        self.manual_escalations.append(ManualEscalation(request.request_id, reason))
