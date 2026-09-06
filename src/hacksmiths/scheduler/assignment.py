"""N-seat interviewer assignment - workflow step 6.

This is the "agent" that fills the panel, and it is **fully deterministic** - no
LLM anywhere. Given a fixed interview time and the set of interviewers still
feasible at that time, it:

1. ranks them by ``(rolling 7-day confirmed count ASC, last-assigned time ASC,
   id)`` - burnout prevention first, round-robin tie-break;
2. offers each open seat to the next-ranked person not already offered/holding a
   seat on this interview and not already declined for that seat, reserving their
   row in the :class:`ReservationLedger` at the moment the offer is created;
3. on a decline or an offer timeout, releases that seat's reservation and cascades
   it to the next-ranked person - **that seat only**, the others are untouched;
4. when every eligible person for a seat is exhausted, marks the seat
   ``exhausted`` and escalates the whole request to manual scheduling.

"Bounded output + fallback" (the first-prompt requirement, minus the LLM): the
only interviewers it can pick are ones in the feasible set for the fixed time;
its fallback is the cascade; its terminal fallback is escalation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Sequence, Set

from .config import SchedulingConfig
from .escalation import escalate_to_manual_scheduling
from .models import Interview, InterviewRequest, InterviewSeat, Round
from .providers.interfaces import InterviewerLoadProvider, NotificationProvider
from .reservations import ReservationLedger
from .timeutils import buffered_interval, ensure_utc


class SeatError(Exception):
    """Raised on an illegal seat operation (e.g. responding to a non-offered seat)."""


@dataclass
class AssignmentOutcome:
    interview: Interview
    request: InterviewRequest  # status becomes manual_scheduling_required on exhaustion
    status: str  # "assigning_panel" | "panel_complete" | "manual_scheduling_required"
    reason: Optional[str] = None


def rank_interviewers(
    interviewer_ids: Sequence[str],
    load_provider: InterviewerLoadProvider,
    as_of: datetime,
    exclude: Set[str] | None = None,
) -> List[str]:
    """Deterministic order: lowest rolling load first, then least-recently-assigned.

    Someone never assigned (``last_assigned_at is None``) sorts ahead of anyone who
    has been. Final tie-break on id keeps the order stable.
    """

    exclude = exclude or set()
    as_of = ensure_utc(as_of)
    never = datetime.min.replace(tzinfo=timezone.utc)

    def key(interviewer_id: str):
        snap = load_provider.get_load_snapshot(interviewer_id, as_of)
        last = ensure_utc(snap.last_assigned_at) if snap.last_assigned_at else never
        return (snap.rolling_confirmed_count, last, interviewer_id)

    return sorted((i for i in interviewer_ids if i not in exclude), key=key)


class PanelAssignmentAgent:
    def __init__(
        self,
        *,
        load_provider: InterviewerLoadProvider,
        reservations: ReservationLedger,
        notifier: NotificationProvider,
        config: SchedulingConfig | None = None,
    ) -> None:
        self.load = load_provider
        self.reservations = reservations
        self.notifier = notifier
        self.config = config or SchedulingConfig()

    # -- internal helpers ---------------------------------------------------

    def _held_ids(self, seats: Sequence[InterviewSeat]) -> Set[str]:
        return {
            s.interviewer_id
            for s in seats
            if s.interviewer_id and s.status in ("offered", "accepted")
        }

    def _pick_next(
        self,
        *,
        ranked: Sequence[str],
        exclude: Set[str],
        res_start: datetime,
        res_end: datetime,
    ) -> Optional[str]:
        for interviewer_id in ranked:
            if interviewer_id in exclude:
                continue
            if not self.reservations.is_free(interviewer_id, res_start, res_end):
                continue
            return interviewer_id
        return None

    def _resolve(
        self, interview: Interview, request: InterviewRequest, now: datetime
    ) -> AssignmentOutcome:
        if interview.has_exhausted_seat:
            exhausted = [s.seat_index for s in interview.seats if s.status == "exhausted"]
            reason = (
                f"panel assignment failed for interview {interview.interview_id}: "
                f"seat(s) {exhausted} at {ensure_utc(interview.slot_start).isoformat()} - "
                f"the qualified interviewer pool for the seat is exhausted (everyone "
                f"eligible has declined, is unavailable, or is already reserved)"
            )
            updated_request = escalate_to_manual_scheduling(request, reason, self.notifier)
            interview = interview.model_copy(
                update={"status": "manual_scheduling_required", "updated_at": now}
            )
            return AssignmentOutcome(interview, updated_request, "manual_scheduling_required", reason)

        if interview.all_seats_accepted:
            interview = interview.model_copy(
                update={"status": "panel_complete", "updated_at": now}
            )
            self.notifier.send_panel_complete(interview)
            return AssignmentOutcome(interview, request, "panel_complete")

        return AssignmentOutcome(interview, request, "assigning_panel")

    # -- public API -------------------------------------------------------

    def fill_pending_seats(
        self,
        *,
        interview: Interview,
        request: InterviewRequest,
        round_: Round,
        feasible_ids_at_slot: Sequence[str],
        now: Optional[datetime] = None,
    ) -> AssignmentOutcome:
        """Offer every ``pending`` seat to the next-ranked feasible interviewer.

        Used both for the initial parallel offer and for re-offering a single seat
        after a decline / timeout / interviewer cancellation.
        """

        as_of = ensure_utc(now or datetime.now(timezone.utc))
        ranked = rank_interviewers(feasible_ids_at_slot, self.load, as_of)
        res_start, res_end = buffered_interval(interview.slot_start, interview.slot_end, round_)
        timeout = timedelta(minutes=self.config.assignment.offer_timeout_minutes)
        seats = [s.model_copy(deep=True) for s in interview.seats]

        for seat in seats:
            if seat.status != "pending":
                continue
            exclude = self._held_ids(seats) | set(seat.declined_interviewer_ids)
            picked = self._pick_next(
                ranked=ranked, exclude=exclude, res_start=res_start, res_end=res_end
            )
            if picked is None:
                seat.status = "exhausted"
                seat.responded_at = as_of
                continue
            self.reservations.reserve(
                picked, interview.interview_id, seat.seat_index, res_start, res_end
            )
            seat.interviewer_id = picked
            seat.status = "offered"
            seat.offered_at = as_of
            seat.offer_expires_at = as_of + timeout
            seat.responded_at = None
            self.notifier.send_seat_offer(interview, seat)

        interview = interview.model_copy(update={"seats": seats, "updated_at": as_of})
        return self._resolve(interview, request, as_of)

    def handle_seat_response(
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
        """Apply an interviewer's accept / decline to their offered seat."""

        as_of = ensure_utc(now or datetime.now(timezone.utc))
        seats = [s.model_copy(deep=True) for s in interview.seats]
        seat = seats[seat_index]
        if seat.status != "offered":
            raise SeatError(
                f"seat {seat_index} is {seat.status!r}, not 'offered' - cannot record a response"
            )

        if accepted:
            seat.status = "accepted"
            seat.responded_at = as_of
            self.notifier.send_seat_filled(interview, seat)
            interview = interview.model_copy(update={"seats": seats, "updated_at": as_of})
            return self._resolve(interview, request, as_of)

        # decline -> release, remember, cascade this one seat
        declined_id = seat.interviewer_id
        self.reservations.release(declined_id, interview.interview_id, seat.seat_index)
        self.notifier.send_seat_released(interview, seat, reason=f"{declined_id} declined the offer")
        seat.declined_interviewer_ids = [*seat.declined_interviewer_ids, declined_id]
        seat.interviewer_id = None
        seat.status = "pending"
        seat.offered_at = None
        seat.offer_expires_at = None
        seat.responded_at = as_of

        interview = interview.model_copy(update={"seats": seats, "updated_at": as_of})
        return self.fill_pending_seats(
            interview=interview,
            request=request,
            round_=round_,
            feasible_ids_at_slot=feasible_ids_at_slot,
            now=as_of,
        )

    def process_timeouts(
        self,
        *,
        interview: Interview,
        request: InterviewRequest,
        round_: Round,
        feasible_ids_at_slot: Sequence[str],
        now: Optional[datetime] = None,
    ) -> AssignmentOutcome:
        """Expire any ``offered`` seat past ``offer_expires_at`` and cascade it."""

        as_of = ensure_utc(now or datetime.now(timezone.utc))
        seats = [s.model_copy(deep=True) for s in interview.seats]
        touched = False
        for seat in seats:
            if seat.status != "offered" or not seat.offer_expires_at:
                continue
            if as_of < ensure_utc(seat.offer_expires_at):
                continue
            timed_out_id = seat.interviewer_id
            self.reservations.release(timed_out_id, interview.interview_id, seat.seat_index)
            self.notifier.send_seat_released(
                interview, seat, reason=f"{timed_out_id} did not respond before the offer expired"
            )
            seat.declined_interviewer_ids = [*seat.declined_interviewer_ids, timed_out_id]
            seat.interviewer_id = None
            seat.status = "pending"
            seat.offered_at = None
            seat.offer_expires_at = None
            seat.responded_at = as_of
            touched = True

        interview = interview.model_copy(update={"seats": seats, "updated_at": as_of})
        if not touched:
            return self._resolve(interview, request, as_of)
        return self.fill_pending_seats(
            interview=interview,
            request=request,
            round_=round_,
            feasible_ids_at_slot=feasible_ids_at_slot,
            now=as_of,
        )
