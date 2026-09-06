"""``ResendNotificationProvider`` — the real
``app.scheduling.providers.interfaces.NotificationProvider`` used by the demo
backend (``app/scheduling/service.py``), replacing an inbox-only mock.

Every hook dual-writes: the same in-app inbox entry as before (so
``/scheduling/notifications`` and the Notifications page are unchanged),
*plus* a real email via ``service.send_email``. Priority per
Documentation/IMPLEMENTATION_PLAN.md Phase 1 is the three candidate/recruiter
-facing ones (escalation, panel-complete); seat-offer/filled/released to
interviewers use the same mechanism, just lower priority to get right first.

**Email failures never propagate.** These hooks run *inside* the pure
scheduling engine's own state transitions (``escalation.py``,
``assignment.py``'s cascade, ``state_machine.py``) — a Resend outage or an
unresolvable recipient must never turn a successful scheduling decision into
a 500 for whoever happened to trigger it. The in-app inbox write already
above this call always succeeds (in-memory), so nothing is silently lost —
worst case, the real email just doesn't go out, and that's logged.
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

from app.scheduling.models import Interview, InterviewRequest, InterviewSeat
from app.scheduling.providers.interfaces import InterviewerRepository, NotificationProvider
from app.scheduling.timeutils import ensure_utc

from .inbox import InboxNotificationProvider
from .service import EmailSendError, send_email

logger = logging.getLogger(__name__)


class ResendNotificationProvider(NotificationProvider):
    def __init__(
        self,
        interviewer_repo: InterviewerRepository,
        resolve_recruiter_email: Callable[[str], Optional[str]],
        resolve_recruiter_identity: Callable[[str], Optional[str]],
    ) -> None:
        """``resolve_recruiter_email(request_id)`` and
        ``resolve_recruiter_identity(request_id)`` are callables, not dicts -
        the DB-backed service (Phase 2) queries the `Interview` row for
        these; nothing here needs to know that. The identity one feeds the
        in-app inbox only (a user id), the email one is what an actual
        escalation email goes to.
        """
        self._interviewer_repo = interviewer_repo
        self._resolve_recruiter_email = resolve_recruiter_email
        # Composed, not subclassed: every hook below still writes here first,
        # so the in-app inbox (`for_recipient`, used by /scheduling/notifications)
        # behaves exactly as it did before real email existed.
        self._inbox = InboxNotificationProvider(resolve_recruiter_identity)

    def for_recipient(self, *identities: str):
        return self._inbox.for_recipient(*identities)

    # -- recipient resolution -------------------------------------------------

    def _interviewer_email(self, interviewer_id: Optional[str]) -> Optional[str]:
        if not interviewer_id:
            return None
        try:
            return self._interviewer_repo.get_interviewer(interviewer_id).email
        except Exception:  # noqa: BLE001 - deliberately broad, see module docstring
            logger.warning("Couldn't resolve email for interviewer_id=%r", interviewer_id)
            return None

    def _recruiter_email(self, request_id: str) -> Optional[str]:
        email = self._resolve_recruiter_email(request_id)
        if not email:
            logger.warning("No recruiter email on file for request_id=%r", request_id)
        return email

    def _send_safe(self, to: Optional[str], subject: str, body_html: str) -> None:
        if not to:
            return
        try:
            send_email(to, subject, body_html)
        except EmailSendError:
            logger.warning("Email send failed (to=%s, subject=%r)", to, subject, exc_info=True)

    # -- NotificationProvider hooks -------------------------------------------

    def send_seat_offer(self, interview: Interview, seat: InterviewSeat) -> None:
        self._inbox.send_seat_offer(interview, seat)
        when = ensure_utc(interview.slot_start).isoformat()
        self._send_safe(
            self._interviewer_email(seat.interviewer_id),
            f"Interview panel seat — {interview.interview_type.replace('_', ' ')}",
            f"<p>You've been offered a panel seat on a {interview.interview_type.replace('_', ' ')} "
            f"interview at {when}.</p><p>Log in to WorkHire to accept or decline.</p>",
        )

    def send_seat_filled(self, interview: Interview, seat: InterviewSeat) -> None:
        self._inbox.send_seat_filled(interview, seat)
        when = ensure_utc(interview.slot_start).isoformat()
        self._send_safe(
            self._interviewer_email(seat.interviewer_id),
            f"You're confirmed — {interview.interview_type.replace('_', ' ')}",
            f"<p>You're confirmed for the {interview.interview_type.replace('_', ' ')} interview "
            f"at {when}.</p>",
        )

    def send_seat_released(self, interview: Interview, seat: InterviewSeat, reason: str) -> None:
        self._inbox.send_seat_released(interview, seat, reason)
        if seat.interviewer_id:
            self._send_safe(
                self._interviewer_email(seat.interviewer_id),
                f"Panel seat released — {interview.interview_type.replace('_', ' ')}",
                f"<p>Your seat on the {interview.interview_type.replace('_', ' ')} interview was "
                f"released: {reason}</p>",
            )

    def send_panel_complete(self, interview: Interview) -> None:
        self._inbox.send_panel_complete(interview)
        when = ensure_utc(interview.slot_start).isoformat()
        for seat in interview.seats:
            self._send_safe(
                self._interviewer_email(seat.interviewer_id),
                f"Panel confirmed — {interview.interview_type.replace('_', ' ')}",
                f"<p>Panel confirmed for the {interview.interview_type.replace('_', ' ')} interview "
                f"at {when}.</p>",
            )
        # Candidate-facing — priority #3 per Phase 1 (candidate booking confirmation).
        self._send_safe(
            interview.candidate_id,
            "Your interview is confirmed",
            f"<p>Good news — your interview is fully confirmed for <strong>{when}</strong>.</p>"
            f"<p>You'll receive a calendar invite with the meeting link once it's created.</p>",
        )

    def send_interview_cancelled(self, interview: Interview, reason: str) -> None:
        self._inbox.send_interview_cancelled(interview, reason)
        for seat in interview.seats:
            self._send_safe(
                self._interviewer_email(seat.interviewer_id),
                f"Interview cancelled — {interview.interview_type.replace('_', ' ')}",
                f"<p>This interview was cancelled: {reason}</p>",
            )
        self._send_safe(
            interview.candidate_id,
            "Your interview was cancelled",
            f"<p>Your interview was cancelled: {reason}</p>",
        )

    def notify_recruiter_manual_scheduling(self, request: InterviewRequest, reason: str) -> None:
        self._inbox.notify_recruiter_manual_scheduling(request, reason)
        # Candidate-facing — priority #2 per Phase 1 (escalation notice), sent
        # to the recruiter who owns the request, not the candidate themselves;
        # the candidate sees FeasibilityResult.candidate_message in-app instead
        # (Documentation/IMPLEMENTATION_PLAN.md Phase 0.6) — deliberately not
        # duplicated as an email to avoid alarming them with a raw escalation.
        self._send_safe(
            self._recruiter_email(request.request_id),
            f"Needs manual scheduling — request {request.request_id}",
            f"<p>Interview request <strong>{request.request_id}</strong> needs manual scheduling:</p>"
            f"<p>{reason}</p>",
        )
