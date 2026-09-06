"""Interview lifecycle state machine (workflow steps 6 & 8).

Interview status::

    assigning_panel ─► panel_complete            (all N seats accepted)
                    ─► manual_scheduling_required (a seat's cascade exhausted)
                    ─► cancelled
    panel_complete  ─► assigning_panel           (one interviewer cancelled; that
                                                  seat re-opens and re-cascades)
                    ─► cancelled
    manual_scheduling_required ─► (terminal for automation)
    cancelled                  ─► (terminal)

Seat mechanics (offer / accept / cascade) live in :class:`PanelAssignmentAgent`;
this class owns creation, the conflict re-check, and the exception paths from
step 8 (candidate cancel / reschedule, single-interviewer cancel).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import List, Optional, Sequence

from .assignment import AssignmentOutcome, PanelAssignmentAgent, SeatError
from .models import (
    FeasibleSlot,
    Interview,
    InterviewRequest,
    InterviewSeat,
    Round,
)
from .providers.interfaces import NotificationProvider
from .reservations import ReservationLedger
from .timeutils import buffered_interval, ensure_utc

__all__ = [
    "InvalidTransitionError",
    "BookingConflictError",
    "SeatError",
    "InterviewStateMachine",
]


class InvalidTransitionError(Exception):
    """Raised when an interview is asked to move between incompatible states."""


class BookingConflictError(Exception):
    """Raised when the pre-finalisation conflict re-check fails."""


_ALLOWED: dict[str, set[str]] = {
    "assigning_panel": {"panel_complete", "manual_scheduling_required", "cancelled"},
    "panel_complete": {"assigning_panel", "cancelled"},
    "manual_scheduling_required": set(),
    "cancelled": set(),
}


def _check_transition(current: str, target: str) -> None:
    if target not in _ALLOWED.get(current, set()):
        raise InvalidTransitionError(f"cannot move interview from {current!r} to {target!r}")


class InterviewStateMachine:
    def __init__(
        self,
        reservations: ReservationLedger,
        notifier: NotificationProvider,
        agent: PanelAssignmentAgent,
    ) -> None:
        self.reservations = reservations
        self.notifier = notifier
        self.agent = agent

    # -- creation --------------------------------------------------------------

    def create_interview(
        self,
        request: InterviewRequest,
        chosen_slot: FeasibleSlot,
        round_: Round,  # noqa: ARG002 - kept for signature symmetry / future use
        now: Optional[datetime] = None,
    ) -> Interview:
        """Open an ``assigning_panel`` interview with N empty (``pending``) seats."""

        moment = ensure_utc(now or datetime.now(timezone.utc))
        seats = [InterviewSeat(seat_index=i) for i in range(request.panelists_required)]
        return Interview(
            interview_id=f"interview-{uuid.uuid4().hex[:12]}",
            request_id=request.request_id,
            candidate_id=request.candidate_id,
            interview_type=request.interview_type,
            hiring_manager_email=request.hiring_manager_email,
            slot_start=ensure_utc(chosen_slot.start),
            slot_end=ensure_utc(chosen_slot.end),
            seats=seats,
            status="assigning_panel",
            created_at=moment,
            updated_at=moment,
        )

    # -- panel assignment (delegates to the agent) --------------------------

    def assign_panel(
        self,
        *,
        interview: Interview,
        request: InterviewRequest,
        round_: Round,
        feasible_ids_at_slot: Sequence[str],
        now: Optional[datetime] = None,
    ) -> AssignmentOutcome:
        return self.agent.fill_pending_seats(
            interview=interview,
            request=request,
            round_=round_,
            feasible_ids_at_slot=feasible_ids_at_slot,
            now=now,
        )

    def respond_to_seat(
        self,
        *,
        interview: Interview,
        request: InterviewRequest,
        round_: Round,
        seat_index: int,
        accepted: bool,
        feasible_ids_at_slot: Sequence[str],
        now: Optional[datetime] = None,
    ) -> AssignmentOutcome:
        return self.agent.handle_seat_response(
            interview=interview,
            request=request,
            round_=round_,
            seat_index=seat_index,
            accepted=accepted,
            feasible_ids_at_slot=feasible_ids_at_slot,
            now=now,
        )

    def process_offer_timeouts(
        self,
        *,
        interview: Interview,
        request: InterviewRequest,
        round_: Round,
        feasible_ids_at_slot: Sequence[str],
        now: Optional[datetime] = None,
    ) -> AssignmentOutcome:
        return self.agent.process_timeouts(
            interview=interview,
            request=request,
            round_=round_,
            feasible_ids_at_slot=feasible_ids_at_slot,
            now=now,
        )

    # -- conflict re-check before event creation ---------------------------

    def verify_ready_to_finalize(self, interview: Interview, round_: Round) -> None:
        """Re-check, just before handing off to event creation, that the booking holds.

        Every seat must be ``accepted`` and its interviewer must still hold the
        reservation for this interview's buffered slot. Raises
        :class:`BookingConflictError` otherwise.
        """

        if interview.status != "panel_complete":
            raise BookingConflictError(
                f"interview {interview.interview_id} is {interview.status!r}, not 'panel_complete'"
            )
        res_start, res_end = buffered_interval(interview.slot_start, interview.slot_end, round_)
        for seat in interview.seats:
            if seat.status != "accepted" or not seat.interviewer_id:
                raise BookingConflictError(f"seat {seat.seat_index} is not accepted")
            if not self.reservations.holds(
                seat.interviewer_id, interview.interview_id, seat.seat_index
            ):
                raise BookingConflictError(
                    f"reservation for seat {seat.seat_index} ({seat.interviewer_id}) is missing"
                )
            if _other_holder_overlaps(
                self.reservations, seat.interviewer_id, interview.interview_id, res_start, res_end
            ):
                raise BookingConflictError(
                    f"another booking overlaps seat {seat.seat_index} ({seat.interviewer_id})"
                )

    # -- step 8 exception paths ------------------------------------------------

    def candidate_cancel(
        self,
        interview: Interview,
        now: Optional[datetime] = None,
        reason: str = "candidate cancelled the interview",
    ) -> Interview:
        """Release ALL seats, notify everyone, terminal ``cancelled``."""

        _check_transition(interview.status, "cancelled")
        moment = ensure_utc(now or datetime.now(timezone.utc))
        self.reservations.release_interview(interview.interview_id)
        updated = interview.model_copy(update={"status": "cancelled", "updated_at": moment})
        self.notifier.send_interview_cancelled(updated, reason)
        return updated

    def candidate_reschedule(
        self,
        interview: Interview,
        request: InterviewRequest,
        now: Optional[datetime] = None,
    ) -> tuple[Interview, InterviewRequest]:
        """Release ALL seats and restart from availability collection (step 3).

        The candidate's chosen time is gone; the caller re-collects new
        availability and re-runs feasibility. Returns
        ``(cancelled_interview, request_reset_to_collecting_availability)``.
        """

        _check_transition(interview.status, "cancelled")
        moment = ensure_utc(now or datetime.now(timezone.utc))
        self.reservations.release_interview(interview.interview_id)
        cancelled = interview.model_copy(
            update={"status": "cancelled", "updated_at": moment}
        )
        for seat in interview.seats:
            if seat.status in ("offered", "accepted"):
                self.notifier.send_seat_released(
                    cancelled, seat, reason="candidate requested a reschedule; collecting new availability"
                )
        updated_request = request.model_copy(update={"status": "collecting_availability"})
        return cancelled, updated_request

    def interviewer_cancel(
        self,
        *,
        interview: Interview,
        request: InterviewRequest,
        round_: Round,
        interviewer_id: str,
        feasible_ids_at_slot: Sequence[str],
        now: Optional[datetime] = None,
    ) -> AssignmentOutcome:
        """One confirmed interviewer backs out: re-open just THAT seat, same time.

        The candidate's time and the other seats are untouched. The freed seat
        cascades through the ranking (excluding the person who cancelled). If its
        pool is exhausted, the request escalates - same as step 6.
        """

        moment = ensure_utc(now or datetime.now(timezone.utc))
        if interview.status not in ("panel_complete", "assigning_panel"):
            raise InvalidTransitionError(
                f"interviewer_cancel not valid from {interview.status!r}"
            )
        seats = [s.model_copy(deep=True) for s in interview.seats]
        seat = next(
            (s for s in seats if s.interviewer_id == interviewer_id and s.status == "accepted"),
            None,
        )
        if seat is None:
            raise SeatError(
                f"{interviewer_id} does not hold an accepted seat on interview {interview.interview_id}"
            )

        self.reservations.release(interviewer_id, interview.interview_id, seat.seat_index)
        seat.declined_interviewer_ids = [*seat.declined_interviewer_ids, interviewer_id]
        seat.interviewer_id = None
        seat.status = "pending"
        seat.offered_at = None
        seat.offer_expires_at = None
        seat.responded_at = moment

        interview = interview.model_copy(
            update={"seats": seats, "status": "assigning_panel", "updated_at": moment}
        )
        self.notifier.send_seat_released(
            interview, seat, reason=f"interviewer {interviewer_id} cancelled after accepting"
        )
        return self.agent.fill_pending_seats(
            interview=interview,
            request=request,
            round_=round_,
            feasible_ids_at_slot=feasible_ids_at_slot,
            now=moment,
        )


def _other_holder_overlaps(
    reservations: ReservationLedger,
    interviewer_id: str,
    own_interview_id: str,
    res_start: datetime,
    res_end: datetime,
) -> bool:
    from .timeutils import intervals_overlap  # local import to avoid cycle noise

    for res in reservations._by_interviewer.get(interviewer_id, []):  # noqa: SLF001 - internal check
        if res.interview_id == own_interview_id:
            continue
        if intervals_overlap(res.start, res.end, res_start, res_end):
            return True
    return False
