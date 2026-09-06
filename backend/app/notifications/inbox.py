"""The in-app notification inbox — what `/scheduling/notifications` reads.

Moved out of ``app/scheduling/store.py`` in Phase 1 (see
Documentation/IMPLEMENTATION_PLAN.md) so ``ResendNotificationProvider``
(``provider.py``) can compose it without a circular import between
``store.py`` and this package. Behavior is unchanged from before — every
engine notification still lands here first, guaranteed, in-memory; real
email is a dual-write on top, not a replacement.

The inbox itself (``self.inbox``) is still an in-process list — notifications
were never meant to be replayed after a restart the way scheduling state is.
It's a **module-level shared list** (``_SHARED_INBOX``), not a fresh one per
instance: Phase 2's ``SchedulingService`` is built fresh per request (state
lives in the DB now, no more singleton store to hang a shared notifier off
of), so every ``InboxNotificationProvider``/``ResendNotificationProvider``
instance still needs to read/write the *same* inbox across requests, or a
notification written during one request would vanish the moment that
request's service object is garbage collected, and ``/scheduling/notifications``
would always see an empty list. Every new instance's ``self.inbox`` is a
reference to that one shared list.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, List, Optional

from app.scheduling.models import Interview, InterviewRequest, InterviewSeat
from app.scheduling.providers.interfaces import NotificationProvider
from app.scheduling.timeutils import ensure_utc

UTC = timezone.utc


@dataclass
class Notification:
    id: str
    recipient: str  # interviewer_id, candidate email, or the recruiter's user id
    kind: str
    message: str
    interview_id: Optional[str]
    created_at: datetime
    read: bool = False


# Process-lifetime, shared by every InboxNotificationProvider instance - see
# the module docstring for why this can't just be a fresh list per instance.
_SHARED_INBOX: List[Notification] = []


def reset_shared_inbox() -> None:
    """Test-only: clear the shared inbox between tests so one test's
    notifications can't leak into another's (`/scheduling/notifications`
    read is unscoped by test, unlike the DB tables which get dropped/recreated
    per test) - see tests/scheduling_api/test_end_to_end.py's fixture."""
    _SHARED_INBOX.clear()


class InboxNotificationProvider(NotificationProvider):
    def __init__(self, resolve_owner: Callable[[str], Optional[str]]) -> None:
        """``resolve_owner(request_id)`` returns the recruiter's identity for
        the in-app inbox (a user id in the DB-backed service, matching what
        ``/scheduling/notifications`` filters by) — a callable, not a dict,
        so both the DB-backed service (Phase 2) and any future in-memory
        caller can supply it without this class caring which."""
        self._resolve_owner = resolve_owner
        self.inbox: List[Notification] = _SHARED_INBOX

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
        owner = self._resolve_owner(request.request_id) or "recruiter"
        self._add(
            owner,
            "escalation",
            f"Interview request {request.request_id} needs manual scheduling: {reason}",
            None,
        )
