"""``DbReservationLedger`` - the DB-backed double-booking guard, replacing
``reservations.ReservationLedger``'s in-memory dict for the live app.

Same public surface as :class:`ReservationLedger` (``is_free``, ``reserve``,
``release``, ``release_interview``, ``holds``) - the pure engine
(``assignment.py``, ``state_machine.py``) calls these duck-typed, with no
import of this module, so this is a drop-in swap at the one wiring point in
``service.py``. **Not** an ABC in ``providers/interfaces.py`` because
``ReservationLedger`` itself never was one - it's a concrete dependency
injected directly, not a swappable provider port. (``state_machine.py``'s
``verify_ready_to_finalize`` also reaches into the in-memory ledger's private
``_by_interviewer`` dict directly - nothing calls that method yet, since
Module 7/event-creation doesn't exist until Phase 4, so this class doesn't
need to replicate that private attribute yet. Whoever wires Phase 4 needs to
either add a compatible view here or call verification a different way.)

This *is* DATA_MODEL.md's "assignment transaction" for
:class:`InterviewSlotOffer`: :meth:`reserve` locks the target interviewer's
``InterviewerProfile`` row (``SELECT ... FOR UPDATE``), re-checks no
overlapping ``OFFERED``/confirmed booking exists, then inserts the row.

**Why there's also a plain Python lock here, not just ``with_for_update()``:**
a first version of this shipped with only the DB-level lock and a confident
comment claiming SQLite's coarser whole-database locking would still save it
- a concurrency test (``tests/scheduling_service/test_reservation_concurrency.py``)
promptly proved that false, consistently, not just occasionally. The actual
mechanics: SQLite never blocks a plain ``SELECT`` (there's no read lock to
wait on), so two threads' read-only ``is_free()`` checks both run to
completion, both concluding "free," *before* either one's write - the
write-level lock ``with_for_update()`` degrades to on SQLite only ever
matters once a write is actually issued, which is too late to prevent the
double-check-both-pass race. ``_LOCKS`` (below) is a real, unconditional
mutex per interviewer id, held for the full check-then-insert section, which
is what actually makes this correct **within one process** today (this demo
runs one worker). ``with_for_update()`` stays in the code because it's not
wrong to have, and becomes the thing actually doing the work once this moves
to Postgres with more than one worker process (a Python lock in one process
can't protect against a second process) - see
Documentation/IMPLEMENTATION_PLAN.md Phase 6.
"""

from __future__ import annotations

import threading
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.db.models import Interview as InterviewRow
from app.db.models import InterviewerProfile as InterviewerProfileRow
from app.db.models import InterviewParticipant
from app.db.models import InterviewSlotOffer

from ..timeutils import ensure_utc, intervals_overlap

UTC = timezone.utc

# Process-wide, one lock per interviewer id, created lazily under `_LOCKS_GUARD`
# so two threads racing on a *brand new* interviewer id can't each create and
# hold a different Lock object for the same id.
_LOCKS: dict[str, threading.Lock] = defaultdict(threading.Lock)
_LOCKS_GUARD = threading.Lock()


def _lock_for(interviewer_id: str) -> threading.Lock:
    with _LOCKS_GUARD:
        return _LOCKS[interviewer_id]


class DbReservationLedger:
    def __init__(self, db: Session) -> None:
        self.db = db

    # -- overlap check --------------------------------------------------------

    def _offered_overlap(self, interviewer_id: str, start: datetime, end: datetime) -> bool:
        rows = (
            self.db.query(InterviewSlotOffer)
            .filter(
                InterviewSlotOffer.interviewer_user_id == interviewer_id,
                InterviewSlotOffer.status == "OFFERED",
            )
            .all()
        )
        return any(intervals_overlap(r.proposed_start_utc, r.proposed_end_utc, start, end) for r in rows)

    def _confirmed_overlap(self, interviewer_id: str, start: datetime, end: datetime) -> bool:
        rows = (
            self.db.query(InterviewParticipant, InterviewRow)
            .join(InterviewRow, InterviewParticipant.interview_id == InterviewRow.id)
            .filter(
                InterviewParticipant.user_id == interviewer_id,
                InterviewParticipant.role == "panelist",
                InterviewParticipant.status == "confirmed",
            )
            .all()
        )
        for _participant, interview in rows:
            if interview.confirmed_start_utc is None or interview.confirmed_end_utc is None:
                continue
            b_start = interview.confirmed_start_utc - timedelta(
                minutes=interview.buffer_minutes_before or 0
            )
            b_end = interview.confirmed_end_utc + timedelta(minutes=interview.buffer_minutes_after or 0)
            if intervals_overlap(b_start, b_end, start, end):
                return True
        return False

    def is_free(self, interviewer_id: str, start: datetime, end: datetime) -> bool:
        s, e = ensure_utc(start), ensure_utc(end)
        return not (
            self._offered_overlap(interviewer_id, s, e) or self._confirmed_overlap(interviewer_id, s, e)
        )

    # -- mutations --------------------------------------------------------------

    def reserve(
        self,
        interviewer_id: str,
        interview_id: str,
        seat_index: int,
        start: datetime,
        end: datetime,
    ) -> None:
        s, e = ensure_utc(start), ensure_utc(end)

        # Hold this interviewer's process-wide lock for the entire
        # check-then-insert-then-commit sequence - see the module docstring
        # for why a lock (not just `with_for_update()`) is what's actually
        # doing the work on this dev SQLite DB, and why the commit has to
        # happen *before* the lock releases: a concurrent thread blocked on
        # this same lock must see this reservation as already-committed the
        # instant it gets its turn, not just "already flushed in some other
        # session" (SQLite doesn't share uncommitted writes across
        # connections - flush() alone isn't visible to the next thread's own
        # session/connection).
        with _lock_for(interviewer_id):
            # Real per-row lock on Postgres; a harmless no-op read on SQLite
            # (see module docstring) - kept because it's correct/necessary
            # once this runs against Postgres with more than one worker
            # process, where the Python lock above can't help.
            self.db.query(InterviewerProfileRow).filter(
                InterviewerProfileRow.user_id == interviewer_id
            ).with_for_update().first()

            if not self.is_free(interviewer_id, s, e):
                raise ValueError(
                    f"cannot reserve {interviewer_id} for {interview_id}#{seat_index}: "
                    f"overlapping reservation already held"
                )

            self.db.add(
                InterviewSlotOffer(
                    interview_id=interview_id,
                    seat_index=seat_index,
                    interviewer_user_id=interviewer_id,
                    proposed_start_utc=s,
                    proposed_end_utc=e,
                    status="OFFERED",
                    offered_at=datetime.now(UTC),
                )
            )
            # Commit (not just flush) while still holding the lock: every
            # `reserve()` call site in `service.py` happens before any other
            # pending write in that same request's transaction (verified
            # across select_slot/respond_to_seat/interviewer_cancel), so this
            # never prematurely commits unrelated half-finished state - it
            # only ever commits this offer row a little earlier than the
            # caller's own final commit would have anyway.
            self.db.commit()

    def release(self, interviewer_id: str, interview_id: str, seat_index: int) -> None:
        # Only ever reaches an OFFERED row in practice: a decline (seat still
        # OFFERED) or an interviewer-cancel-after-accept (seat's offer row is
        # already ACCEPTED by then - the confirmed InterviewParticipant row,
        # not this one, is what service.py flips to 'cancelled' for that
        # case). No matching row is a silent no-op either way, matching the
        # in-memory ledger's release() (which never raised on an unknown
        # reservation).
        row = self._find_offer(interviewer_id, interview_id, seat_index, status="OFFERED")
        if row is not None:
            row.status = "DECLINED"
            row.responded_at = datetime.now(UTC)
            self.db.flush()

    def release_interview(self, interview_id: str) -> None:
        """Wipe every hold this interview has on anyone - candidate cancel/
        reschedule (state_machine.py). Unlike :meth:`release`, this must
        cover *both* still-pending offers and already-accepted seats, since
        the old in-memory ledger never distinguished the two (a reservation
        was a reservation from offer through acceptance until explicitly
        released) - service.py doesn't separately touch InterviewParticipant
        for a candidate-initiated cancel, so this is the only place that
        happens.
        """
        offered = (
            self.db.query(InterviewSlotOffer)
            .filter(InterviewSlotOffer.interview_id == interview_id, InterviewSlotOffer.status == "OFFERED")
            .all()
        )
        for row in offered:
            row.status = "RELEASED"
            row.responded_at = datetime.now(UTC)

        confirmed = (
            self.db.query(InterviewParticipant)
            .filter(
                InterviewParticipant.interview_id == interview_id,
                InterviewParticipant.role == "panelist",
                InterviewParticipant.status == "confirmed",
            )
            .all()
        )
        for row in confirmed:
            row.status = "cancelled"

        self.db.flush()

    def holds(self, interviewer_id: str, interview_id: str, seat_index: int) -> bool:
        offer = self._find_offer(interviewer_id, interview_id, seat_index, status="OFFERED")
        if offer is not None:
            return True
        participant = (
            self.db.query(InterviewParticipant)
            .filter(
                InterviewParticipant.interview_id == interview_id,
                InterviewParticipant.user_id == interviewer_id,
                InterviewParticipant.seat_index == seat_index,
                InterviewParticipant.role == "panelist",
                InterviewParticipant.status == "confirmed",
            )
            .first()
        )
        return participant is not None

    def _find_offer(
        self, interviewer_id: str, interview_id: str, seat_index: int, *, status: str
    ) -> Optional[InterviewSlotOffer]:
        return (
            self.db.query(InterviewSlotOffer)
            .filter(
                InterviewSlotOffer.interview_id == interview_id,
                InterviewSlotOffer.seat_index == seat_index,
                InterviewSlotOffer.interviewer_user_id == interviewer_id,
                InterviewSlotOffer.status == status,
            )
            .order_by(InterviewSlotOffer.offered_at.desc())
            .first()
        )
